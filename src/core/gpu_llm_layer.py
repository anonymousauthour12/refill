
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from huggingface_hub import login

from src.core.config import config


class GPUOutOfMemoryError(Exception):
    """Raised when CUDA VRAM is exhausted during inference."""
    pass


_tokenizer = None
_model = None


def gpu_llm_init():
    """Load the HuggingFace model and tokenizer onto the GPU (or CPU if no GPU)."""
    global _tokenizer, _model

    if config.huggingface_access_token:
        login(token=config.huggingface_access_token)

    _tokenizer = AutoTokenizer.from_pretrained(
        config.model,
        trust_remote_code=True
    )

    _model = AutoModelForCausalLM.from_pretrained(
        config.model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )

    _model.eval()


def gpu_get_response(chat_history: list, max_new_tokens: int):
    """
    Run inference on the locally loaded GPU model.

    Returns:
        (reply_text, in_token_count, out_token_count)
        reply_text is None if inference fails for a non-OOM reason.

    Raises:
        GPUOutOfMemoryError: if CUDA VRAM is exhausted.
    """
    global _tokenizer, _model

    if _tokenizer is None or _model is None:
        return None, 0, 0

    try:
        text = _tokenizer.apply_chat_template(
            chat_history,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = _tokenizer(text, return_tensors="pt").to(_model.device)
        in_tokens = int(inputs["input_ids"].shape[1])

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        with torch.no_grad():
            outputs = _model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False
            )

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        generated_tokens = outputs[0][in_tokens:]
        out_tokens = int(len(generated_tokens))
        reply = _tokenizer.decode(generated_tokens, skip_special_tokens=True)

        return reply, in_tokens, out_tokens

    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        raise GPUOutOfMemoryError(
            f"GPU out of memory running '{config.model}' — prompt too large for available VRAM"
        )
    except Exception:
        return None, 0, 0
