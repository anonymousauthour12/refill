
from copy import deepcopy
import random
import re
from openai import AzureOpenAI
import time
import openai
import os
import pickle
import threading
import json
import fcntl

from src.core.config import config

from openai import OpenAI
from anthropic import AnthropicFoundry
import anthropic

try:
    from src.core import gpu_llm_layer as _gpu_llm_layer
except ImportError:
    _gpu_llm_layer = None

_AZURE_MODELS = {"gpt-5", "gpt-4o", "Llama-3.3-70B-Instruct"}

def _is_azure_model(model_name: str) -> bool:
    return model_name in _AZURE_MODELS or model_name.startswith("claude")


client = ""
anthropic_client = None

class ContextTooLargeError(Exception):
    """Raised when a prompt exceeds the model's context window."""
    pass


class _TokenRateLimiter:
    """
    Proactive sliding-window TPM limiter.
    File-backed so it works across parallel processes (xargs -P N).
    Falls back gracefully if the lock file is inaccessible.
    """
    _WINDOW = 60.0

    def __init__(self, tpm_limit: int, state_file: str = "/tmp/llm_rate_limiter.json"):
        self.limit = tpm_limit
        self.state_file = state_file
        self.lock_file = state_file + ".lock"
        self._local_lock = threading.Lock()

    total_wait_ms: float = 0.0

    def acquire(self, estimated_tokens: int):
        while True:
            with self._local_lock:
                try:
                    with open(self.lock_file, "w") as lf:
                        fcntl.flock(lf, fcntl.LOCK_EX)
                        now = time.time()
                        try:
                            with open(self.state_file) as f:
                                window = json.load(f)
                        except (FileNotFoundError, json.JSONDecodeError):
                            window = []
                        window = [[t, tok] for t, tok in window if now - t < self._WINDOW]
                        used = sum(tok for _, tok in window)
                        if used + estimated_tokens <= self.limit:
                            window.append([now, estimated_tokens])
                            with open(self.state_file, "w") as f:
                                json.dump(window, f)
                            return
                        wait = (self._WINDOW - (now - window[0][0]) + 0.2) if window else self._WINDOW
                except Exception:
                    return  # if file locking fails, let the API handle it
            sleep = min(wait, 5)
            time.sleep(sleep)
            self.total_wait_ms += sleep * 1000

    def correct_last(self, estimated: int, actual: int):
        """Replace the estimated token count for the most recent entry with the real value."""
        if estimated == actual:
            return
        with self._local_lock:
            try:
                with open(self.lock_file, "w") as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        with open(self.state_file) as f:
                            window = json.load(f)
                    except (FileNotFoundError, json.JSONDecodeError):
                        return
                    if window:
                        window[-1][1] = actual
                        with open(self.state_file, "w") as f:
                            json.dump(window, f)
            except Exception:
                pass

    def reset(self):
        try:
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
        except Exception:
            pass


def _endpoint_to_state_file(endpoint: str) -> str:
    clean = re.sub(r'[^\w]', '_', endpoint.rstrip('/'))
    clean = re.sub(r'_+', '_', clean).strip('_')
    return f"/tmp/llm_rate_limiter_{clean[-60:]}.json"

_rate_limiter = _TokenRateLimiter(tpm_limit=240_000)

def llm_init():

    global client, anthropic_client, _rate_limiter

    _rate_limiter = _TokenRateLimiter(
        tpm_limit=int(config.tpm_limit * 0.95),
        state_file=_endpoint_to_state_file(config.azure_endpoint)
    )
    _rate_limiter.reset()

    if config.model.startswith("claude"):
        anthropic_client = AnthropicFoundry(
            api_key=config.api_key,
            base_url=config.azure_endpoint,
            timeout=300
        )

    elif config.model == "Llama-3.3-70B-Instruct":
        client = OpenAI(
            base_url=config.azure_endpoint,
            api_key=config.api_key,
            timeout=300
        )

    elif config.model in {"gpt-4o", "gpt-5"}:
        client = AzureOpenAI(
            api_key=config.api_key,
            api_version=config.api_version,
            azure_endpoint=config.azure_endpoint,
            timeout=300
        )
    else:
        if _gpu_llm_layer is None:
            raise ImportError(
                f"torch/transformers not installed; cannot run GPU model '{config.model}'"
            )
        _gpu_llm_layer.gpu_llm_init()

chat_histories = {}

global_chat_history = []

chat_histories["global"] = global_chat_history




def flush_chat_history(chat_history_key = "global"):
    global chat_histories
    chat_histories[chat_history_key] = []

def add_chat_history_key_if_not_exists(chat_history_key = "global"):
    if chat_history_key not in chat_histories:
        flush_chat_history(chat_history_key)

def add_message(role, content, chat_history_key: str = "global"):
    global chat_histories
    if role not in ("user", "assistant"):
        raise ValueError("Role must be 'user' or 'assistant'")
    add_chat_history_key_if_not_exists(chat_history_key)
    chat_histories[chat_history_key].append({"role": role, "content": content})
    return chat_histories[chat_history_key]

def get_number_of_llm_items(chat_history_key: str = "global"):
    return len(chat_histories[chat_history_key])

from dataclasses import dataclass

def _log_warning(message: str):
    if not config.work_space:
        return
    try:
        with open(os.path.join(config.work_space, "warnings.log"), "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass

@dataclass
class LLMPerformanceMetrics:
    number_of_calls_to_LLM: int = 0
    total_LLM_time: int = 0
    number_of_chars_to_LLM: int = 0
    number_of_chars_from_LLM: int = 0
    actual_in_tokens: int = 0
    actual_out_tokens: int = 0
    rate_limit_hits: int = 0

llm_metrics = LLMPerformanceMetrics()

start_timestamp = 0
def set_start_timestamp():
    global start_timestamp
    start_timestamp = int(time.time() * 1000)

def get_response(user_input: str, chat_history_key: str = "global", update_chat_history: bool =True, use_chat_history: bool = True):


    global chat_histories

    if chat_history_key == "any":
        flush_chat_history("any")
    
    # current timestamp in milliseconds
    

    llm_metrics.number_of_calls_to_LLM += 1
    set_start_timestamp()
    llm_metrics.number_of_chars_to_LLM += len(user_input)
    add_message("user", user_input, chat_history_key)

    # Prompt profiling — write every prompt to prompt_log.txt in work_space
    if config.work_space:
        try:
            import os as _os
            _call_idx = llm_metrics.number_of_calls_to_LLM
            _estimated_tokens = len(user_input) // 4
            _separator = f"\n{'='*80}\n"
            _header = (f"CALL #{_call_idx} | key={chat_history_key} | "
                       f"strategy={config.strategy} | model={config.model} | "
                       f"~{_estimated_tokens:,} tokens\n{'-'*80}\n")
            with open(_os.path.join(config.work_space, "prompt_log.txt"), "a") as _f:
                _f.write(_separator + _header + user_input + "\n")
        except Exception:
            pass

    chat_history_to_send = []
    if use_chat_history:
        chat_history_to_send = chat_histories[chat_history_key]
    else:
        chat_history_to_send.append({"role": "user", "content": user_input})
    

    seed_value = 12345
    assistant_reply = None

    # Proactive context length check — raise before wasting an API call
    input_chars = sum(len(m["content"]) for m in chat_history_to_send)
    estimated_input_tokens = input_chars // 4
    if estimated_input_tokens > config.max_context_tokens:
        raise ContextTooLargeError(
            f"Estimated prompt tokens ({estimated_input_tokens:,}) exceed limit ({config.max_context_tokens:,})"
        )

    estimated_tokens = estimated_input_tokens + config.max_tokens

    if _is_azure_model(config.model):
        _rate_limiter.acquire(estimated_tokens)

    for attempt in range(100):
        try:
            if config.model.startswith("claude"):
                active_anthropic = anthropic_client
                anthropic_params = {
                    "model": config.model,
                    "messages": chat_history_to_send,
                    "max_tokens": config.max_tokens,
                }
                response = active_anthropic.messages.create(**anthropic_params)
                assistant_reply = response.content[0].text
                actual_in  = response.usage.input_tokens
                actual_out = response.usage.output_tokens
            elif config.model == "gpt-4o":
                active_client = client
                response = active_client.chat.completions.create(
                    model=config.model,
                    messages=chat_history_to_send,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    frequency_penalty=config.frequency_penalty,
                    seed=seed_value,
                    presence_penalty=config.presence_penalty,
                    stream=False
                )
                assistant_reply = response.choices[0].message.content
                actual_in  = response.usage.prompt_tokens
                actual_out = response.usage.completion_tokens
            elif config.model == "gpt-5":
                active_client = client
                response = active_client.chat.completions.create(
                    model=config.model,
                    messages=chat_history_to_send,
                    temperature=1,
                    frequency_penalty=config.frequency_penalty,
                    seed=seed_value,
                    presence_penalty=config.presence_penalty,
                    stream=False
                )
                assistant_reply = response.choices[0].message.content
                actual_in  = response.usage.prompt_tokens
                actual_out = response.usage.completion_tokens
            elif config.model == "Llama-3.3-70B-Instruct":
                active_client = client
                print(f"Sending request to {config.model}")
                response = active_client.chat.completions.create(
                    model=config.model,
                    messages=chat_history_to_send,
                    temperature=config.temperature,
                    frequency_penalty=config.frequency_penalty,
                    seed=seed_value,
                    presence_penalty=config.presence_penalty,
                    stream=False
                )
                assistant_reply = response.choices[0].message.content
                actual_in  = response.usage.prompt_tokens
                actual_out = response.usage.completion_tokens
            elif not _is_azure_model(config.model):
                if _gpu_llm_layer is None:
                    raise ImportError(
                        f"torch/transformers not installed; cannot run GPU model '{config.model}'"
                    )
                try:
                    assistant_reply, actual_in, actual_out = _gpu_llm_layer.gpu_get_response(
                        chat_history_to_send, config.max_tokens
                    )
                except _gpu_llm_layer.GPUOutOfMemoryError as e:
                    raise ContextTooLargeError(str(e))
            else:
                print("Not supported model")
                exit()
            llm_metrics.actual_in_tokens  += actual_in
            llm_metrics.actual_out_tokens += actual_out
            if _is_azure_model(config.model):
                _rate_limiter.correct_last(estimated_tokens, actual_in + actual_out)
            break  # success
        except (openai.BadRequestError, anthropic.BadRequestError) as e:
            if any(kw in str(e).lower() for kw in ("context", "token", "length")):
                raise ContextTooLargeError(str(e))
            raise
        except (openai.RateLimitError, anthropic.RateLimitError):
            wait_time = 60 if attempt >= 6 else 2 ** attempt
            llm_metrics.rate_limit_hits += 1
            print(f"Rate limit hit. Retrying in {wait_time} seconds...")
            _log_warning(f"RATE_LIMIT_HIT | attempt={attempt} | wait={wait_time}s | model={config.model}")
            # Charge the full window to the active limiter so other parallel workers
            # on the same key also back off.
            _rate_limiter.acquire(_rate_limiter.limit)
            time.sleep(wait_time)
            _rate_limiter.total_wait_ms += wait_time * 1000
        except (anthropic.InternalServerError, openai.InternalServerError) as e:
            wait_time = 30 if attempt >= 6 else 2 ** attempt
            print(f"InternalServerError (HTTP 500). Retrying in {wait_time} seconds...")
            _log_warning(f"INTERNAL_SERVER_ERROR | attempt={attempt} | wait={wait_time}s | error={e}")
            time.sleep(wait_time)
            _rate_limiter.total_wait_ms += wait_time * 1000

    if assistant_reply is None:
        # All retries exhausted without a successful response — remove the user message
        # we added to the history and return None so callers can handle it gracefully.
        try:
            chat_histories[chat_history_key].pop()
        except Exception:
            pass
        return None

    if update_chat_history and use_chat_history:
        add_message("assistant", assistant_reply, chat_history_key)
    else:
        chat_histories[chat_history_key].pop()
    llm_metrics.number_of_chars_from_LLM += len(assistant_reply)
    llm_metrics.total_LLM_time += int(time.time() * 1000)
    llm_metrics.total_LLM_time -= start_timestamp

    return assistant_reply

