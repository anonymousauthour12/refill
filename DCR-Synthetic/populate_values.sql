-- populate_values.sql
--
-- Fills the 185 derived columns of DCR-Synthetic with the values given by their formulas.
-- Run it after alter_tables.sql, in one session (mysql < populate_values.sql), because
-- some columns build temporary tables.
--
-- Order: the 124 columns of the first release, the 40 hard columns (iterative algorithms),
-- and the 21 columns added last.
-- Needs MySQL 8.0 (window functions, recursive CTEs). The iterative columns take a few minutes each
-- and the largest updates (Financial_ijs.trans, oulad.studentVle, YelpDataset3.Reviews) up to an hour.
-- sql_mode is not strict because a few formulas cast text such as '1997/II' to a number;
-- the leading digits are kept, as in the stored values.


SET SESSION max_execution_time = 0;
SET SESSION sql_safe_updates = 0;
SET SESSION cte_max_recursion_depth = 100000;
SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION';


-- Part 1: the 124 columns of the first release

USE `NCAA_S`;

-- NCAA_S.regular_season_detailed_results.score_diff: Margin of victory: winning team score minus losing team score
UPDATE regular_season_detailed_results SET score_diff = wscore - lscore;

-- NCAA_S.regular_season_detailed_results.game_type: Game type: whether a college basketball game was decided in regulation time or required one or more overtime periods
UPDATE regular_season_detailed_results SET game_type = CASE WHEN numot > 0 THEN 'Overtime' ELSE 'Regulation' END;

-- NCAA_S.regular_season_detailed_results.matchup_label: Matchup label for this college basketball game formed by concatenating the winning and losing team names retrieved via two parallel FK joins to the teams table through the wteam and lteam columns
UPDATE regular_season_detailed_results r
JOIN teams wt ON r.wteam = wt.team_id
JOIN teams lt ON r.lteam = lt.team_id
SET r.matchup_label = CONCAT(wt.team_name, ' vs ', lt.team_name);

-- NCAA_S.tourney_seeds.seed_region_code: Single character extracted from the fixed first position of the NCAA tournament seed string encoding the bracket region where W X Y and Z each represent one of the four tournament regions
UPDATE tourney_seeds SET seed_region_code = LEFT(seed, 1);

-- NCAA_S.tourney_seeds.seed_number: Numeric tournament seed rank extracted from character positions two and three of the seed string and cast to an unsigned integer giving the seeding of the team within its bracket region from 1 for top seed to 16 for bottom seed
UPDATE tourney_seeds SET seed_number = CAST(SUBSTRING(seed, 2, 2) AS UNSIGNED);

USE `lahman_2014_S`;

-- lahman_2014_S.seriespost.total_games: Total playoff series games played: wins plus losses
UPDATE seriespost SET total_games = wins + losses;

-- lahman_2014_S.batting.total_bases: Total bases earned by a batter: singles count once, doubles twice, triples three times, home runs four times
UPDATE batting SET total_bases = H + `2B` + 2 * `3B` + 3 * HR;

-- lahman_2014_S.pitching.innings_pitched: Innings pitched converted from outs recorded: IPouts divided by 3 since each inning contains 3 outs
UPDATE pitching SET innings_pitched = ROUND(IPouts / 3, 1);

-- lahman_2014_S.teams.pythag_win_pct: Pythagorean win expectancy: predicted team win percentage derived from runs scored and runs allowed using the formula R squared divided by the sum of R squared and RA squared
UPDATE teams SET pythag_win_pct = ROUND(POWER(R, 2) / NULLIF(POWER(R, 2) + POWER(RA, 2), 0), 3);

-- lahman_2014_S.players.bmi: Body Mass Index in imperial units: 703 multiplied by weight in pounds divided by height in inches squared
UPDATE players SET bmi = ROUND(703.0 * weight / NULLIF(POWER(height, 2), 0), 1);

-- lahman_2014_S.players.full_name: Player full name: first name and last name concatenated with null-safe handling for missing first names
UPDATE players SET full_name = CONCAT(COALESCE(nameFirst, ''), ' ', nameLast);

-- lahman_2014_S.players.preferred_name: Player preferred name: the name a baseball player is known by using their nickname when recorded otherwise falling back to their given first name
UPDATE players SET preferred_name = COALESCE(nameNick, nameFirst);

-- lahman_2014_S.teams.season_result: Season result: highest playoff achievement of a baseball team in a given year evaluated in priority order from World Series winner down to no playoff appearance
UPDATE teams SET season_result = CASE WHEN WSWin = 'Y' THEN 'World Series Winner' WHEN LgWin = 'Y' THEN 'League Champion' WHEN DivWin = 'Y' THEN 'Division Winner' WHEN WCWin = 'Y' THEN 'Wild Card' ELSE 'No Playoff' END;

-- lahman_2014_S.teams.win_pct: Win percentage derived via Pythagorean expectancy using runs scored and runs allowed: the column name suggests simple W/G but the stored values follow the Bill James formula R squared over the sum of R squared and RA squared - REFILL must distinguish between the two candidate formulas by validating against the data
UPDATE teams SET win_pct = ROUND(POWER(R, 2) / NULLIF(POWER(R, 2) + POWER(RA, 2), 0), 3);

-- lahman_2014_S.pitching.strikeout_rate: Strikeout rate expressed as strikeouts per nine innings: the column name suggests the modern per-batter-faced proportion SO divided by BFP but the stored values follow the traditional K/9 formula - REFILL must reject the K% candidate after validation and converge on the correct formula
UPDATE pitching SET strikeout_rate = ROUND(9 * SO / NULLIF(IPouts / 3.0, 0), 2);

-- lahman_2014_S.batting.batting_avg_change: Change in batting average between consecutive stints within the same season: stint is a guaranteed consecutive counter starting at 1 for each player-year so no correlated subquery is needed - captures performance shift after a mid-season trade
UPDATE batting b1 JOIN batting b2 ON b1.playerID = b2.playerID AND b1.yearID = b2.yearID AND b1.stint = b2.stint + 1 SET b1.batting_avg_change = ROUND(b1.H / NULLIF(b1.AB, 0), 3) - ROUND(b2.H / NULLIF(b2.AB, 0), 3);

-- lahman_2014_S.salaries.salary_change: Player salary change from the last recorded contract year on the same team: uses a correlated subquery to find the most recent prior yearID because players may skip years between contracts
WITH sub AS (
    SELECT playerID, teamID, yearID, lgID,
           salary - LAG(salary) OVER (PARTITION BY playerID, teamID ORDER BY yearID) AS val
    FROM salaries
)
UPDATE salaries s1
JOIN sub ON s1.playerID = sub.playerID AND s1.teamID = sub.teamID
     AND s1.yearID = sub.yearID AND s1.lgID = sub.lgID
SET s1.salary_change = sub.val;

-- lahman_2014_S.teams.wins_improvement: Team wins improvement from the last recorded season: uses a correlated subquery to find the most recent prior yearID because franchise gaps and relocations make the year sequence non-consecutive
WITH sub AS (
    SELECT yearID, teamID, lgID,
           W - LAG(W) OVER (PARTITION BY teamID ORDER BY yearID) AS val
    FROM teams
)
UPDATE teams t1
JOIN sub ON t1.yearID = sub.yearID AND t1.teamID = sub.teamID AND t1.lgID = sub.lgID
SET t1.wins_improvement = sub.val;

-- lahman_2014_S.teams.total_payroll: Total salary payroll for all players on the team in a given season
UPDATE teams t SET t.total_payroll = (SELECT SUM(s.salary) FROM salaries s WHERE s.teamID = t.teamID AND s.yearID = t.yearID);

-- lahman_2014_S.players.career_hr_best_season: Highest number of home runs hit by this player in any single season of their career
UPDATE players p SET p.career_hr_best_season = (SELECT MAX(b.HR) FROM batting b WHERE b.playerID = p.playerID);

-- lahman_2014_S.batting.player_birth_country: Country of birth for this batter copied from the players table to enable origin-based analysis within the batting records
UPDATE batting b JOIN players p ON b.playerID = p.playerID SET b.player_birth_country = p.birthCountry;

-- lahman_2014_S.batting.team_win_pct: Win percentage of the team this batter played for in the given season computed from wins and games played in the teams table
UPDATE batting b JOIN teams t ON b.teamID = t.teamID AND b.yearID = t.yearID SET b.team_win_pct = ROUND(t.W / NULLIF(t.G, 0), 3);

-- lahman_2014_S.batting.batter_handedness: Batting handedness of this player decoded from the single-letter bats code in the players table into a readable label of Right Left or Switch
UPDATE batting b JOIN players p ON b.playerID = p.playerID SET b.batter_handedness = CASE WHEN p.bats = 'R' THEN 'Right' WHEN p.bats = 'L' THEN 'Left' ELSE 'Switch' END;

-- lahman_2014_S.batting.player_team_label: Player and team label for this batting record formed by concatenating the player last name from the players table and the team full name from the teams table via two parallel FK joins
UPDATE batting b JOIN players p ON b.playerID = p.playerID JOIN teams t ON b.teamID = t.teamID AND b.yearID = t.yearID SET b.player_team_label = CONCAT(p.nameLast, ' (', t.name, ')');

-- lahman_2014_S.batting.hr_rank_in_season: Home run rank of this batting record among all batting records in the same season using RANK so ties share the same rank and the next rank is skipped
WITH _cte AS (
    SELECT playerID, yearID, stint,
           RANK() OVER (PARTITION BY yearID ORDER BY HR DESC) AS _val
    FROM batting
)
UPDATE batting b
JOIN _cte ON b.playerID = _cte.playerID AND b.yearID = _cte.yearID AND b.stint = _cte.stint
SET b.hr_rank_in_season = _cte._val;

-- lahman_2014_S.batting.cumulative_career_hr: Cumulative total home runs in this player career up to and including this batting record ordered by year and stint using a running SUM with ROWS UNBOUNDED PRECEDING
WITH _cte AS (
    SELECT playerID, yearID, stint,
           SUM(HR) OVER (PARTITION BY playerID ORDER BY yearID, stint ROWS UNBOUNDED PRECEDING) AS _val
    FROM batting
)
UPDATE batting b
JOIN _cte ON b.playerID = _cte.playerID AND b.yearID = _cte.yearID AND b.stint = _cte.stint
SET b.cumulative_career_hr = _cte._val;

-- lahman_2014_S.schools.alumni_career_batting_games: Total number of career batting game appearances by all MLB players who attended this college computed by traversing schools to schoolsplayers via schoolID and then to batting via playerID and summing the G column across all alumni records
UPDATE schools s
SET s.alumni_career_batting_games = (
    SELECT COALESCE(SUM(b.G), 0)
    FROM schoolsplayers sp
    JOIN batting b ON sp.playerID = b.playerID
    WHERE sp.schoolID = s.schoolID
);

USE `YelpDataset3_S`;

-- YelpDataset3_S.Reviews.votes_total: Total engagement votes on a review: funny votes plus useful votes plus cool votes
UPDATE Reviews SET votes_total = votes_funny + votes_useful + votes_cool;

-- YelpDataset3_S.Business.city_state: Business location label: city and state concatenated with a comma and space separator
UPDATE Business SET city_state = CONCAT(city, ', ', state);

-- YelpDataset3_S.Reviews.sentiment: Review sentiment: three-tier sentiment label derived from the star rating mapping 4-5 stars to Positive 3 stars to Neutral and 1-2 stars to Negative
UPDATE Reviews SET sentiment = CASE WHEN stars >= 4 THEN 'Positive' WHEN stars >= 3 THEN 'Neutral' ELSE 'Negative' END;

-- YelpDataset3_S.Business.avg_useful_votes: Average number of useful votes received per review for this business
UPDATE Business b SET b.avg_useful_votes = ROUND((SELECT AVG(r.votes_useful) FROM Reviews r WHERE r.business_id = b.business_id), 2);

-- YelpDataset3_S.Business.positive_reviews: Number of reviews with four or more stars received by this business capturing only positive sentiment reviews
UPDATE Business b SET b.positive_reviews = (SELECT COUNT(*) FROM Reviews r WHERE r.business_id = b.business_id AND r.stars >= 4);

-- YelpDataset3_S.Reviews.user_review_sequence: Sequential review number for this reviewer ordered by review date then review id so the first review they submitted receives number 1
WITH _cte AS (
    SELECT review_id,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY review_date, review_id) AS _val
    FROM Reviews
)
UPDATE Reviews r
JOIN _cte ON r.review_id = _cte.review_id
SET r.user_review_sequence = _cte._val;

USE `Basketball_men_S`;

-- Basketball_men_S.players_teams.field_goal_pct: Field goal shooting percentage: shots made divided by shots attempted rounded to 3 decimal places
UPDATE players_teams SET field_goal_pct = ROUND(fgMade / NULLIF(fgAttempted, 0), 3);

-- Basketball_men_S.players_teams.season_scoring_rank: Scoring rank of this player stint among all player stints in the same NBA season using DENSE_RANK so ties share the same rank and no rank values are skipped
WITH _cte AS (
    SELECT playerID, year, stint, tmID,
           DENSE_RANK() OVER (PARTITION BY year ORDER BY points DESC) AS _val
    FROM players_teams
)
UPDATE players_teams pt
JOIN _cte ON pt.playerID = _cte.playerID AND pt.year = _cte.year AND pt.stint = _cte.stint AND pt.tmID = _cte.tmID
SET pt.season_scoring_rank = _cte._val;

-- Basketball_men_S.players_teams.prev_season_points: Points scored by this player in their immediately preceding stint record ordered by year and stint so the first stint of each player career has NULL for this column
WITH _cte AS (
    SELECT playerID, year, stint, tmID,
           LAG(points) OVER (PARTITION BY playerID ORDER BY year, stint) AS _val
    FROM players_teams
)
UPDATE players_teams pt
JOIN _cte ON pt.playerID = _cte.playerID AND pt.year = _cte.year AND pt.stint = _cte.stint AND pt.tmID = _cte.tmID
SET pt.prev_season_points = _cte._val;

-- Basketball_men_S.players.primary_position_code: Single character extracted from the first non-whitespace position of the position code string encoding the primary playing position of the basketball player where F is Forward G is Guard and C is Center
UPDATE players SET primary_position_code = LEFT(TRIM(pos), 1);

-- Basketball_men_S.players.is_multi_position: Binary flag indicating whether the player is listed under more than one position decoded from the position code string by checking for a dash separator where 1 means multi-position 0 means single-position and NULL means position is unknown
UPDATE players SET is_multi_position = CASE WHEN pos IS NULL THEN NULL WHEN pos LIKE '%-%' THEN 1 ELSE 0 END;

-- Basketball_men_S.players.position_count: Total number of positions listed for this player counted by measuring how many dash separators appear in the trimmed position code string and adding one since N positions are separated by N minus 1 dashes
UPDATE players SET position_count = LENGTH(TRIM(pos)) - LENGTH(REPLACE(TRIM(pos), '-', '')) + 1;

USE `Financial_ijs_S`;

-- Financial_ijs_S.loans.monthly_payment: Monthly loan repayment instalment: total loan amount divided by duration in months
UPDATE loans SET monthly_payment = ROUND(amount / NULLIF(duration, 0), 2);

-- Financial_ijs_S.clients.birth_number_formatted: Formatted Czech birth number: YYMMDD digits split into YY/MM/DD format using positional string extraction
UPDATE clients SET birth_number_formatted = CONCAT(LEFT(birth_number, 2), '/', SUBSTRING(birth_number, 3, 2), '/', SUBSTRING(birth_number, 5, 2));

-- Financial_ijs_S.cards.issue_date: Card issue date: descriptive rename of the issued date column using standard banking terminology
UPDATE cards SET issue_date = issued;

-- Financial_ijs_S.loans.loan_end_date: Loan maturity date computed by adding the loan duration in months to the loan start date
UPDATE loans SET loan_end_date = DATE_ADD(date, INTERVAL duration MONTH);

-- Financial_ijs_S.trans.transaction_label: Transaction label: the most descriptive available category for a bank transaction falling back from specific payment symbol to operation type with blank strings treated as NULL
UPDATE trans SET transaction_label = COALESCE(NULLIF(TRIM(k_symbol), ''), NULLIF(TRIM(operation), ''), type);

-- Financial_ijs_S.loans.loan_status_label: Loan status label: readable description of the loan outcome decoded from the single-letter PKDD status code A B C or D
UPDATE loans SET loan_status_label = CASE WHEN status = 'A' THEN 'Running OK' WHEN status = 'B' THEN 'Running Defaulted' WHEN status = 'C' THEN 'Finished OK' WHEN status = 'D' THEN 'Finished Defaulted' ELSE 'Unknown' END;

-- Financial_ijs_S.trans.days_since_last_transaction: Days since the previous bank transaction on the same account: correlated subquery finds the most recent prior transaction ID because transaction IDs are globally assigned and not consecutive per account
WITH sub AS (
    SELECT id,
           DATEDIFF(date, LAG(date) OVER (PARTITION BY account_id ORDER BY id)) AS val
    FROM trans
)
UPDATE trans t1
JOIN sub ON t1.id = sub.id
SET t1.days_since_last_transaction = sub.val;

-- Financial_ijs_S.accounts.transactions: Number of transactions recorded on this bank account
UPDATE accounts a SET a.transactions = (SELECT COUNT(*) FROM trans t WHERE t.account_id = a.id);

-- Financial_ijs_S.accounts.total_credited: Total amount credited to this bank account across all incoming transactions of type PRIJEM
UPDATE accounts a SET a.total_credited = (SELECT SUM(t.amount) FROM trans t WHERE t.account_id = a.id AND t.type = 'PRIJEM');

-- Financial_ijs_S.accounts.largest_transaction: Largest single transaction amount recorded on this bank account
UPDATE accounts a SET a.largest_transaction = (SELECT MAX(t.amount) FROM trans t WHERE t.account_id = a.id);

-- Financial_ijs_S.trans.days_after_account_opened: Number of days elapsed between account opening and this transaction computed by DATEDIFF between the transaction date and the account creation date fetched from the accounts table
UPDATE trans t JOIN accounts a ON t.account_id = a.id SET t.days_after_account_opened = DATEDIFF(t.date, a.date);

-- Financial_ijs_S.trans.district_crime_per_resident: Number of crimes per 1000 inhabitants in the district of the account that issued this transaction computed from crime count and population columns in the districts table via two sequential FK hops through accounts
UPDATE trans t JOIN accounts a ON t.account_id = a.id JOIN districts d ON a.district_id = d.id SET t.district_crime_per_resident = ROUND(d.A16 / NULLIF(d.A4, 0) * 1000, 2);

-- Financial_ijs_S.trans.transaction_sequence: Chronological sequence number of this transaction within its account ordered by transaction date then by transaction id as tiebreaker assigning 1 to the oldest transaction
WITH _cte AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY date, id) AS _val
    FROM trans
)
UPDATE trans t
JOIN _cte ON t.id = _cte.id
SET t.transaction_sequence = _cte._val;

-- Financial_ijs_S.trans.prev_transaction_amount: Transaction amount from the immediately preceding transaction on the same account ordered by date then id so this column is NULL for the first transaction on each account
WITH _cte AS (
    SELECT id,
           LAG(amount) OVER (PARTITION BY account_id ORDER BY date, id) AS _val
    FROM trans
)
UPDATE trans t
JOIN _cte ON t.id = _cte.id
SET t.prev_transaction_amount = _cte._val;

-- Financial_ijs_S.trans.running_credit_total: Running total of all credit deposits into this account up to and including this transaction computed as a conditional sum that accumulates only PRIJEM type transactions and ignores VYDAJ debits ordered by date and transaction id
WITH _cte AS (
    SELECT id,
           SUM(CASE WHEN type = 'PRIJEM' THEN amount ELSE 0 END)
               OVER (PARTITION BY account_id ORDER BY date, id ROWS UNBOUNDED PRECEDING) AS _val
    FROM trans
)
UPDATE trans t
JOIN _cte ON t.id = _cte.id
SET t.running_credit_total = _cte._val;

-- Financial_ijs_S.clients.birth_year: Four-digit birth year reconstructed from the two-digit prefix of the Czech birth number by adding 1900 to the cast integer since all clients in this dataset were born between 1911 and 1987
UPDATE clients SET birth_year = 1900 + CAST(LEFT(birth_number, 2) AS UNSIGNED);

-- Financial_ijs_S.clients.client_gender: Biological sex of the client decoded from the month digits of the Czech birth number where digits greater than 50 indicate female because 50 is added to the month for women and digits 1 through 12 indicate male
UPDATE clients SET client_gender = IF(CAST(SUBSTRING(birth_number, 3, 2) AS UNSIGNED) > 50, 'Female', 'Male');

-- Financial_ijs_S.clients.birth_month: Actual birth month recovered from the Czech birth number by extracting the two-digit month field and applying modulo 50 which removes the 50 offset added for female clients and returns the true calendar month from 1 to 12 for both sexes
UPDATE clients SET birth_month = CAST(SUBSTRING(birth_number, 3, 2) AS UNSIGNED) % 50;

-- Financial_ijs_S.trans.trans_district_name: Name of the district where the account linked to this transaction is registered fetched by traversing the two-hop path from trans to accounts via account_id and then from accounts to districts via district_id
UPDATE trans t
JOIN accounts a ON t.account_id = a.id
JOIN districts d ON a.district_id = d.id
SET t.trans_district_name = d.A2;

-- Financial_ijs_S.loans.account_transaction_count: Total number of transactions recorded on the bank account linked to this loan computed by traversing loans to accounts via account_id and then counting all trans rows linked to that account via account_id
UPDATE loans l
SET l.account_transaction_count = (
    SELECT COUNT(*)
    FROM trans t
    JOIN accounts a ON t.account_id = a.id
    WHERE a.id = l.account_id
);

-- Financial_ijs_S.loans.account_owner_birth_year: Birth year of the primary account owner of this loan reconstructed from the Czech birth number by traversing three hops from loans to accounts via account_id then to disps filtering on OWNER type via account_id then to clients via client_id and adding 1900 to the two-digit year prefix
UPDATE loans l JOIN accounts a ON l.account_id = a.id JOIN disps di ON a.id = di.account_id AND di.type = 'OWNER' JOIN clients c ON di.client_id = c.id SET l.account_owner_birth_year = 1900 + CAST(LEFT(c.birth_number, 2) AS UNSIGNED);

-- Financial_ijs_S.cards.card_holder_district_name: Name of the district of the bank account associated with this credit card retrieved by traversing three hops from cards to disps via disp_id then from disps to accounts via account_id then from accounts to districts via district_id
UPDATE cards c JOIN disps di ON c.disp_id = di.id JOIN accounts a ON di.account_id = a.id JOIN districts d ON a.district_id = d.id SET c.card_holder_district_name = d.A2;

USE `Mondial_S`;

-- Mondial_S.province.pop_density: Population density: number of inhabitants per square kilometre in this province
UPDATE province SET pop_density = ROUND(Population / NULLIF(Area, 0), 2);

-- Mondial_S.organization.founding_date: Organization founding date: exact copy of the Established date column stored under a more descriptive name
UPDATE organization SET founding_date = Established;

-- Mondial_S.politics.independence_year: Year in which a country gained independence extracted from the stored independence date
UPDATE politics SET independence_year = YEAR(Independence);

-- Mondial_S.river.outlet_name: River outlet name: the name of the body of water a river flows into resolved by priority - sea first then lake then parent river - covering all 218 rivers with no NULL result
UPDATE river SET outlet_name = COALESCE(Sea, Lake, River);

-- Mondial_S.river.outlet_river_length: Length of the river this tributary flows into: fetched via the self-referencing River column which stores the name of the outlet river in the same river table
UPDATE river r1 JOIN river r2 ON r1.River = r2.Name SET r1.outlet_river_length = r2.Length;

-- Mondial_S.river.tributary_length_fraction: Tributary length as a fraction of the outlet river length: ratio of the current river row length to the length of the river it flows into via the self-referencing River column
UPDATE river r1 JOIN river r2 ON r1.River = r2.Name SET r1.tributary_length_fraction = ROUND(r1.Length / NULLIF(r2.Length, 0), 3);

-- Mondial_S.river.exceeds_outlet_length: Flag indicating whether this river is longer than the river it flows into: CASE compares the current river length against the outlet river length retrieved via the self-referencing River column
UPDATE river r1 JOIN river r2 ON r1.River = r2.Name SET r1.exceeds_outlet_length = CASE WHEN r1.Length > r2.Length THEN 1 ELSE 0 END;

-- Mondial_S.country.provinces: Number of provinces belonging to this country
UPDATE country c SET c.provinces = (SELECT COUNT(*) FROM province p WHERE p.Country = c.Code);

-- Mondial_S.continent.avg_country_pop_density: Average population density of countries within this continent weighted by the percentage of each country land area that falls within the continent combining population and area from the country table with percentage weights from the encompasses table
UPDATE continent cn
SET cn.avg_country_pop_density = (
    SELECT ROUND(SUM(co.Population / NULLIF(co.Area, 0) * en.Percentage) / NULLIF(SUM(en.Percentage), 0), 2)
    FROM encompasses en
    JOIN country co ON en.Country = co.Code
    WHERE en.Continent = cn.Name AND co.Area > 0
);

USE `stats_S`;

-- stats_S.users.reputation_log: Log base 10 of user reputation score to produce a compressed scale suitable for skewed distributions
UPDATE users SET reputation_log = ROUND(LOG10(GREATEST(Reputation, 1)), 3);

-- stats_S.users.active_days: Number of days between account creation and last access measuring total active lifespan of the account
UPDATE users SET active_days = DATEDIFF(LastAccessDate, CreationDate);

-- stats_S.posts.activity_span_days: Number of days from post creation to last recorded activity measuring the post engagement lifespan
UPDATE posts SET activity_span_days = DATEDIFF(LasActivityDate, CreaionDate);

-- stats_S.posts.post_type_label: Post type label: human-readable post category decoded from the numeric PostTypeId code using the Stack Exchange data dictionary
UPDATE posts SET post_type_label = CASE WHEN PostTypeId = 1 THEN 'Question' WHEN PostTypeId = 2 THEN 'Answer' ELSE 'Other' END;

-- stats_S.posts.question_score: Score of the question this answer was posted to: fetched via the self-referencing ParentId foreign key which links each answer post to its question post in the same table
UPDATE posts p1 JOIN posts p2 ON p1.ParentId = p2.Id SET p1.question_score = p2.Score;

-- stats_S.posts.accepted_answer_score: Score of the accepted answer for this question: fetched via the self-referencing AcceptedAnswerId foreign key which links a question post to the answer post that was accepted
UPDATE posts q JOIN posts a ON q.AcceptedAnswerId = a.Id SET q.accepted_answer_score = a.Score;

-- stats_S.posts.answer_score_delta: Answer score minus the question score it was posted to: arithmetic difference between the current answer row and the question row it references via ParentId in the same posts table
UPDATE posts p1 JOIN posts p2 ON p1.ParentId = p2.Id SET p1.answer_score_delta = p1.Score - p2.Score;

-- stats_S.posts.is_accepted_answer: Flag indicating whether this answer was selected as the accepted answer by its question: CASE compares the answer Id against the AcceptedAnswerId stored in the referenced question row
UPDATE posts p1 JOIN posts p2 ON p1.ParentId = p2.Id SET p1.is_accepted_answer = CASE WHEN p2.AcceptedAnswerId = p1.Id THEN 1 ELSE 0 END;

-- stats_S.users.avg_post_score: Average score across all posts authored by this user on the Stack Exchange platform
UPDATE users u SET u.avg_post_score = ROUND((SELECT AVG(p.Score) FROM posts p WHERE p.OwnerUserId = u.Id), 2);

-- stats_S.comments.post_author_tenure_at_post_time: Number of days the post author had been registered on the site when they created the post being commented on computed from post creation date and user registration date via two sequential FK hops through posts to users
UPDATE comments c JOIN posts p ON c.PostId = p.Id JOIN users u ON p.OwnerUserId = u.Id SET c.post_author_tenure_at_post_time = DATEDIFF(p.CreaionDate, u.CreationDate);

-- stats_S.posts.user_post_rank: Rank of this post within the author entire post history ordered from highest to lowest score using RANK so the most upvoted post gets rank 1
WITH _cte AS (
    SELECT Id,
           RANK() OVER (PARTITION BY OwnerUserId ORDER BY Score DESC) AS _val
    FROM posts
)
UPDATE posts p
JOIN _cte ON p.Id = _cte.Id
SET p.user_post_rank = _cte._val;

-- stats_S.posts.cumulative_avg_score: Running average of post scores for this author accumulated from their first post up to and including the current post ordered by creation date and rounded to two decimal places
WITH _cte AS (
    SELECT Id,
           ROUND(AVG(Score) OVER (PARTITION BY OwnerUserId ORDER BY CreaionDate ROWS UNBOUNDED PRECEDING), 2) AS _val
    FROM posts
)
UPDATE posts p
JOIN _cte ON p.Id = _cte.Id
SET p.cumulative_avg_score = _cte._val;

-- stats_S.posts.first_tag: First tag name extracted from the Stack Exchange angle-bracket tag string by taking the substring between the first opening and closing angle brackets using nested SUBSTRING_INDEX calls
UPDATE posts SET first_tag = SUBSTRING_INDEX(SUBSTRING_INDEX(Tags, '>', 1), '<', -1);

-- stats_S.posts.tag_count: Total number of tags on this post counted by measuring how many opening angle bracket characters appear in the tag string since each tag contributes exactly one opening bracket in the Stack Exchange angle-bracket format
UPDATE posts SET tag_count = LENGTH(Tags) - LENGTH(REPLACE(Tags, '<', ''));

-- stats_S.comments.post_author_badge_count: Number of community badges earned by the author of the post that this comment was written on retrieved by joining comments to posts via PostId then to users via OwnerUserId and counting the badges linked to that user via UserId
UPDATE comments c
JOIN posts p ON c.PostId = p.Id
JOIN users u ON p.OwnerUserId = u.Id
SET c.post_author_badge_count = (
    SELECT COUNT(*) FROM badges b WHERE b.UserId = u.Id
);

USE `imdb_full_S`;

-- imdb_full_S.actors.actor_gender: Actor gender: exact copy of the sex column stored under a domain-appropriate descriptive name
UPDATE actors SET actor_gender = sex;

-- imdb_full_S.movies.release_year: Release year of the movie extracted from the four-digit year embedded in parentheses at the end of the title string using nested SUBSTRING_INDEX on the opening and closing parentheses and cast to an unsigned integer
UPDATE movies SET release_year = CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(title, '(', -1), ')', 1) AS UNSIGNED);

-- imdb_full_S.actors.actor_last_name: Surname of the actor extracted from the Last comma First formatted name string by taking everything before the first comma using SUBSTRING_INDEX with NULL stored for single-name actors who have no comma in their name
UPDATE actors SET actor_last_name = SUBSTRING_INDEX(name, ',', 1);

-- imdb_full_S.actors.avg_movie_rating: Average IMDB rating across all movies this actor appeared in computed by traversing actors to movies2actors via actorid and then to ratings via movieid and averaging the rank values rounded to one decimal place
UPDATE actors a
SET a.avg_movie_rating = (
    SELECT ROUND(AVG(CAST(r.rank AS DECIMAL(4,1))), 1)
    FROM movies2actors ma
    JOIN ratings r ON ma.movieid = r.movieid
    WHERE ma.actorid = a.actorid
);

USE `ErgastF1_S`;

-- ErgastF1_S.drivers.full_name: Driver full name: forename and surname concatenated with a single space separator
UPDATE drivers SET full_name = CONCAT(forename, ' ', surname);

-- ErgastF1_S.races.season_round_label: Race season label: year and round number combined into a human-readable race identifier string
UPDATE races SET season_round_label = CONCAT(year, ' Round ', round);

-- ErgastF1_S.drivers.date_of_birth: Driver date of birth: full descriptive form of the abbreviated dob date column
UPDATE drivers SET date_of_birth = dob;

-- ErgastF1_S.drivers.birth_year: Birth year of an F1 driver extracted from the date of birth using the YEAR function
UPDATE drivers SET birth_year = YEAR(dob);

-- ErgastF1_S.pitStops.laps_since_last_pitstop: Laps run between consecutive pit stops in the same race: current stop lap number minus the previous stop lap number using a guaranteed consecutive stop sequence key
UPDATE pitStops ps1 JOIN pitStops ps2 ON ps1.raceId = ps2.raceId AND ps1.driverId = ps2.driverId AND ps1.stop = ps2.stop + 1 SET ps1.laps_since_last_pitstop = ps1.lap - ps2.lap;

-- ErgastF1_S.races.days_since_previous_race: Days between consecutive races within the same F1 season: DATEDIFF between the current race date and the previous round date using the guaranteed consecutive round number as the sequence key
UPDATE races r1 JOIN races r2 ON r1.year = r2.year AND r1.round = r2.round + 1 SET r1.days_since_previous_race = DATEDIFF(r1.date, r2.date);

-- ErgastF1_S.pitStops.time_since_previous_pitstop: Clock time elapsed between a driver's consecutive pit stops within the same race: TIMEDIFF between the two pit stop clock times using the guaranteed consecutive stop number as the sequence key
UPDATE pitStops ps1 JOIN pitStops ps2 ON ps1.raceId = ps2.raceId AND ps1.driverId = ps2.driverId AND ps1.stop = ps2.stop + 1 SET ps1.time_since_previous_pitstop = TIMEDIFF(ps1.time, ps2.time);

-- ErgastF1_S.races.days_to_same_round_last_year: Days between the same round number in consecutive F1 seasons capturing calendar drift in the race schedule: DATEDIFF between the current season race date and the same round in the prior season
UPDATE races r1 JOIN races r2 ON r1.round = r2.round AND r1.year = r2.year + 1 SET r1.days_to_same_round_last_year = DATEDIFF(r1.date, r2.date);

-- ErgastF1_S.driverStandings.points_this_race: Points scored by an F1 driver in a single race derived by subtracting the previous cumulative standings total from the current one: correlated subquery required because raceId is a global sequence not consecutive per driver
WITH sub AS (
    SELECT driverStandingsId,
           points - LAG(points) OVER (PARTITION BY driverId ORDER BY raceId) AS val
    FROM driverStandings
)
UPDATE driverStandings ds1
JOIN sub ON ds1.driverStandingsId = sub.driverStandingsId
SET ds1.points_this_race = sub.val;

-- ErgastF1_S.constructorStandings.points_this_race: Points scored by an F1 constructor in a single race derived by subtracting the previous cumulative standings total from the current one: correlated subquery required because raceId is global not consecutive per constructor
WITH sub AS (
    SELECT constructorStandingsId,
           points - LAG(points) OVER (PARTITION BY constructorId ORDER BY raceId) AS val
    FROM constructorStandings
)
UPDATE constructorStandings cs1
JOIN sub ON cs1.constructorStandingsId = sub.constructorStandingsId
SET cs1.points_this_race = sub.val;

-- ErgastF1_S.circuits.races_hosted: Total number of Formula 1 races held at this circuit across all seasons
UPDATE circuits c SET c.races_hosted = (SELECT COUNT(*) FROM races r WHERE r.circuitId = c.circuitId);

-- ErgastF1_S.drivers.avg_finish_position: Average finishing position of this F1 driver across all races entered computed from position order values
UPDATE drivers d SET d.avg_finish_position = ROUND((SELECT AVG(r.positionOrder) FROM results r WHERE r.driverId = d.driverId), 2);

-- ErgastF1_S.circuits.first_race_year: Earliest year in which a Formula 1 race was held at this circuit
UPDATE circuits c SET c.first_race_year = (SELECT MIN(r.year) FROM races r WHERE r.circuitId = c.circuitId);

-- ErgastF1_S.drivers.race_wins: Total number of Formula 1 races won by this driver counting only results where the finishing position equals 1
UPDATE drivers d SET d.race_wins = (SELECT COUNT(*) FROM results r WHERE r.driverId = d.driverId AND r.position = 1);

-- ErgastF1_S.drivers.best_grid_position: Best starting grid position ever achieved by this driver taking the minimum grid value and excluding zero which indicates a non-starter entry
UPDATE drivers d SET d.best_grid_position = (SELECT MIN(r.grid) FROM results r WHERE r.driverId = d.driverId AND r.grid > 0);

-- ErgastF1_S.results.race_year: Race year denormalized from the races table into the results row to enable year-based analysis without joining
UPDATE results r JOIN races ra ON r.raceId = ra.raceId SET r.race_year = ra.year;

-- ErgastF1_S.results.race_era: Formula 1 regulatory era of this race result classified from the race year fetched from the races table into four historical engine formula periods
UPDATE results r JOIN races ra ON r.raceId = ra.raceId SET r.race_era = CASE WHEN ra.year < 1980 THEN 'Classic Era' WHEN ra.year < 2000 THEN 'Turbo Era' WHEN ra.year < 2014 THEN 'V8 Era' ELSE 'Hybrid Era' END;

-- ErgastF1_S.results.driver_age_at_race: Age of the F1 driver in whole years at the time of this race result computed using TIMESTAMPDIFF on the driver date of birth from the drivers table and the race date from the races table via two parallel FK joins from the results row
UPDATE results r JOIN drivers d ON r.driverId = d.driverId JOIN races ra ON r.raceId = ra.raceId SET r.driver_age_at_race = TIMESTAMPDIFF(YEAR, d.dob, ra.date);

-- ErgastF1_S.results.race_constructor_label: Label combining the race year from the races table and the constructor name from the constructors table into a single identifier for this result via two parallel FK joins from the results row
UPDATE results r JOIN races ra ON r.raceId = ra.raceId JOIN constructors co ON r.constructorId = co.constructorId SET r.race_constructor_label = CONCAT(ra.year, ' ', co.name);

-- ErgastF1_S.results.driver_career_race_number: Sequential career race number for this driver ordered by raceId so the first race they entered receives number 1 and each subsequent race increments by 1
WITH _cte AS (
    SELECT resultId,
           ROW_NUMBER() OVER (PARTITION BY driverId ORDER BY raceId) AS _val
    FROM results
)
UPDATE results r
JOIN _cte ON r.resultId = _cte.resultId
SET r.driver_career_race_number = _cte._val;

-- ErgastF1_S.races.next_race_name: Name of the following race in the same Formula 1 season retrieved using LEAD over races ordered by round so the final race of each season has NULL for this column
WITH _cte AS (
    SELECT raceId,
           LEAD(name) OVER (PARTITION BY year ORDER BY round) AS _val
    FROM races
)
UPDATE races r
JOIN _cte ON r.raceId = _cte.raceId
SET r.next_race_name = _cte._val;

-- ErgastF1_S.lapTimes.lap_time_rank: Rank of this driver among all drivers competing in the same race on the same lap ordered by their individual lap time in milliseconds with rank 1 assigned to the fastest driver on that specific lap independently of overall race position
WITH _cte AS (
    SELECT raceId, driverId, lap,
           RANK() OVER (PARTITION BY raceId, lap ORDER BY milliseconds) AS _val
    FROM lapTimes
)
UPDATE lapTimes lt
JOIN _cte ON lt.raceId = _cte.raceId AND lt.driverId = _cte.driverId AND lt.lap = _cte.lap
SET lt.lap_time_rank = _cte._val;

-- ErgastF1_S.lapTimes.positions_gained_on_lap: Number of positions this driver gained or lost on this lap relative to the previous lap computed as the difference between the previous lap position and the current lap position so positive values mean positions gained negative values mean positions lost and the first lap of each driver in each race is NULL because there is no preceding lap
WITH _cte AS (
    SELECT raceId, driverId, lap,
           LAG(position) OVER (PARTITION BY raceId, driverId ORDER BY lap) - position AS _val
    FROM lapTimes
)
UPDATE lapTimes lt
JOIN _cte ON lt.raceId = _cte.raceId AND lt.driverId = _cte.driverId AND lt.lap = _cte.lap
SET lt.positions_gained_on_lap = _cte._val;

-- ErgastF1_S.pitStops.pitstop_constructor_name: Name of the constructor that entered this pit stop retrieved by first joining pitStops to results on raceId and driverId to obtain the constructorId and then joining results to constructors to obtain the constructor name
UPDATE pitStops ps JOIN results r ON ps.raceId = r.raceId AND ps.driverId = r.driverId JOIN constructors co ON r.constructorId = co.constructorId SET ps.pitstop_constructor_name = co.name;

USE `oulad_S`;

-- oulad_S.studentInfo.module_presentation: Course instance identifier: module code and presentation code joined with a hyphen
UPDATE studentInfo SET module_presentation = CONCAT(code_module, '-', code_presentation);

-- oulad_S.studentInfo.pass_flag: Student pass flag: binary outcome indicator set to 1 if the student passed or achieved a distinction and 0 for withdrawal or failure
UPDATE studentInfo SET pass_flag = CASE WHEN final_result IN ('Pass', 'Distinction') THEN 1 ELSE 0 END;

-- oulad_S.studentInfo.total_vle_clicks: Total number of VLE clicks accumulated by this student across all interactions in this module and presentation
UPDATE studentInfo si SET si.total_vle_clicks = (SELECT SUM(sv.sum_click) FROM studentVle sv WHERE sv.id_student = si.id_student AND sv.code_module = si.code_module AND sv.code_presentation = si.code_presentation);

-- oulad_S.studentAssessment.submission_type: Type of assessment this submission belongs to copied from the assessments catalogue into the submission record
UPDATE studentAssessment sa JOIN assessments a ON sa.id_assessment = a.id_assessment SET sa.submission_type = a.assessment_type;

-- oulad_S.studentAssessment.days_before_due: Days remaining until the assessment due date at the time of submission computed by subtracting the submission date from the due date stored in the assessments table: negative values indicate late submissions
UPDATE studentAssessment sa JOIN assessments a ON sa.id_assessment = a.id_assessment SET sa.days_before_due = a.date - sa.date_submitted;

-- oulad_S.studentAssessment.assessment_category: Human-readable category of this assessment submission decoded from the assessment_type code in the assessments table into Tutor-Marked Computer-Marked or Exam
UPDATE studentAssessment sa JOIN assessments a ON sa.id_assessment = a.id_assessment SET sa.assessment_category = CASE WHEN a.assessment_type = 'TMA' THEN 'Tutor-Marked' WHEN a.assessment_type = 'CMA' THEN 'Computer-Marked' ELSE 'Exam' END;

-- oulad_S.studentInfo.final_weighted_score: Student final weighted assessment score for this module and presentation computed as the sum of score times weight divided by total weight joining studentAssessment for scores and assessments for weights
UPDATE studentInfo si
SET si.final_weighted_score = (
    SELECT ROUND(SUM(sa.score * a.weight) / NULLIF(SUM(a.weight), 0), 2)
    FROM studentAssessment sa
    JOIN assessments a ON sa.id_assessment = a.id_assessment
    WHERE sa.id_student = si.id_student
      AND a.code_module = si.code_module
      AND a.code_presentation = si.code_presentation
      AND sa.score IS NOT NULL
);

-- oulad_S.studentInfo.semester_code: Single character extracted from the fixed last position of the OULAD course presentation code encoding the semester where J represents the February cohort and B represents the October cohort
UPDATE studentInfo SET semester_code = RIGHT(code_presentation, 1);

-- oulad_S.studentInfo.presentation_year: Four-digit academic year extracted from the first four characters of the presentation code and cast to an unsigned integer giving the calendar year in which the course presentation began
UPDATE studentInfo SET presentation_year = CAST(LEFT(code_presentation, 4) AS UNSIGNED);

-- oulad_S.studentInfo.semester_start_month: Calendar month in which the OULAD course presentation starts decoded from the semester letter in the final character of the presentation code where J presentations start in February and B presentations start in October
UPDATE studentInfo SET semester_start_month = CASE WHEN RIGHT(code_presentation, 1) = 'J' THEN 'February' ELSE 'October' END;

-- oulad_S.studentVle.course_length: Length in days of the course module that this student virtual learning environment interaction belongs to retrieved by first joining studentVle to vle on id_site to get the module and presentation codes and then joining vle to courses to get the course length
UPDATE studentVle sv JOIN vle v ON sv.id_site = v.id_site JOIN courses c ON v.code_module = c.code_module AND v.code_presentation = c.code_presentation SET sv.course_length = c.length;


-- Part 2: the 40 added hard columns (the ground truth of a column is computed into the temporary table m_gt)

USE `NCAA_S`;

-- NCAA_S.regular_season_compact_results.power_gap: SRS with cap, home-court adjustment, time decay, 10 centred iterations
CREATE TEMPORARY TABLE m_gt AS WITH g AS (SELECT c.season, c.wteam, c.lteam, LEAST(GREATEST((c.wscore - c.lscore) - CASE WHEN c.wloc = 'H' THEN 3.5 WHEN c.wloc = 'A' THEN -3.5 ELSE 0 END, -15), 15) AS m, POW(0.5, (mx.md - c.daynum) / 40) AS w FROM NCAA_S.regular_season_compact_results c JOIN (SELECT season AS s2, MAX(daynum) AS md FROM NCAA_S.regular_season_compact_results GROUP BY season) mx ON mx.s2 = c.season), ev AS (SELECT season, wteam AS team, lteam AS opp, m, w FROM g UNION ALL SELECT season, lteam, wteam, -m, w FROM g), mm AS (SELECT season, team, SUM(w * m) / SUM(w) AS am FROM ev GROUP BY season, team), r0 AS (SELECT season, team, am AS rt FROM mm), r1 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r0 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r2 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r1 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r3 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r2 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r4 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r3 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r5 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r4 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r6 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r5 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r7 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r6 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r8 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r7 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r9 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r8 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q), r10 AS (SELECT season, team, raw - AVG(raw) OVER (PARTITION BY season) AS rt FROM (SELECT mm.season, mm.team, mm.am + SUM(ev.w * pv.rt) / SUM(ev.w) AS raw FROM mm JOIN ev ON ev.season = mm.season AND ev.team = mm.team JOIN r9 pv ON pv.season = ev.season AND pv.team = ev.opp GROUP BY mm.season, mm.team, mm.am) q) SELECT c.season AS k1, c.daynum AS k2, c.wteam AS k3, c.lteam AS k4, ROUND(rw.rt - rl.rt, 3) AS derived FROM NCAA_S.regular_season_compact_results c LEFT JOIN r10 rw ON rw.season = c.season AND rw.team = c.wteam LEFT JOIN r10 rl ON rl.season = c.season AND rl.team = c.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`power_gap` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

-- NCAA_S.regular_season_compact_results.strength_balance: Offense-Defense rating (alternating matrix scaling), defence normalised each step, 10 iterations, log ratio of overall ratings
CREATE TEMPORARY TABLE m_A AS SELECT season, i, j, SUM(pts) AS pts FROM (SELECT season, wteam AS i, lteam AS j, wscore AS pts FROM NCAA_S.regular_season_compact_results UNION ALL SELECT season, lteam, wteam, lscore FROM NCAA_S.regular_season_compact_results) x GROUP BY season, i, j;
ALTER TABLE m_A ADD INDEX (season, i), ADD INDEX (season, j);
CREATE TEMPORARY TABLE m_d0 (PRIMARY KEY (season, team)) AS SELECT DISTINCT season, i AS team, 1.0 AS v FROM m_A;
CREATE TEMPORARY TABLE m_o1 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d0 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o1 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d1 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o2 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d1 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o2 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d2 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o3 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d2 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o3 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d3 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o4 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d3 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o4 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d4 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o5 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d4 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o5 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d5 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o6 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d5 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o6 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d6 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o7 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d6 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o7 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d7 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o8 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d7 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o8 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d8 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o9 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d8 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o9 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d9 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_o10 (PRIMARY KEY (season, team)) AS SELECT a.season, a.i AS team, SUM(a.pts / d.v) AS v FROM m_A a JOIN m_d9 d ON d.season = a.season AND d.team = a.j GROUP BY a.season, a.i;
CREATE TEMPORARY TABLE m_draw AS SELECT a.season, a.j AS team, SUM(a.pts / o.v) AS v FROM m_A a JOIN m_o10 o ON o.season = a.season AND o.team = a.i GROUP BY a.season, a.j;
CREATE TEMPORARY TABLE m_d10 (PRIMARY KEY (season, team)) AS SELECT season, team, v / AVG(v) OVER (PARTITION BY season) AS v FROM m_draw;
DROP TEMPORARY TABLE m_draw;
CREATE TEMPORARY TABLE m_R1 (PRIMARY KEY (season, team)) AS SELECT o.season, o.team, o.v / d.v AS r FROM m_o10 o JOIN m_d10 d ON d.season = o.season AND d.team = o.team;
CREATE TEMPORARY TABLE m_R2 (PRIMARY KEY (season, team)) AS SELECT season, team, r FROM m_R1;
CREATE TEMPORARY TABLE m_gt AS SELECT c.season AS k1, c.daynum AS k2, c.wteam AS k3, c.lteam AS k4, ROUND(LN(rw.r) - LN(rl.r), 4) AS derived FROM NCAA_S.regular_season_compact_results c LEFT JOIN m_R1 rw ON rw.season = c.season AND rw.team = c.wteam LEFT JOIN m_R2 rl ON rl.season = c.season AND rl.team = c.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`strength_balance` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_A, m_d0, m_o1, m_draw, m_d1, m_o2, m_d2, m_o3, m_d3, m_o4, m_d4, m_o5, m_d5, m_o6, m_d6, m_o7, m_d7, m_o8, m_d8, m_o9, m_d9, m_o10, m_d10, m_R1, m_R2, m_gt;

-- NCAA_S.regular_season_compact_results.resilience_quotient: Bradley-Terry MM, 8 steps, pseudo-game against a unit opponent, geometric-mean normalised per season, log ratio
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 1.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c1 AS SELECT * FROM m_r0;
ALTER TABLE m_c1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d1 AS SELECT * FROM m_r0;
ALTER TABLE m_d1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d1 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r0 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c1 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c2 AS SELECT * FROM m_r1;
ALTER TABLE m_c2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d2 AS SELECT * FROM m_r1;
ALTER TABLE m_d2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d2 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r1 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c2 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c3 AS SELECT * FROM m_r2;
ALTER TABLE m_c3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d3 AS SELECT * FROM m_r2;
ALTER TABLE m_d3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d3 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r2 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c3 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c4 AS SELECT * FROM m_r3;
ALTER TABLE m_c4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d4 AS SELECT * FROM m_r3;
ALTER TABLE m_d4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d4 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r3 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c4 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c5 AS SELECT * FROM m_r4;
ALTER TABLE m_c5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d5 AS SELECT * FROM m_r4;
ALTER TABLE m_d5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d5 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r4 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c5 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c6 AS SELECT * FROM m_r5;
ALTER TABLE m_c6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d6 AS SELECT * FROM m_r5;
ALTER TABLE m_d6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d6 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r5 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c6 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c7 AS SELECT * FROM m_r6;
ALTER TABLE m_c7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d7 AS SELECT * FROM m_r6;
ALTER TABLE m_d7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d7 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r6 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c7 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c8 AS SELECT * FROM m_r7;
ALTER TABLE m_c8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d8 AS SELECT * FROM m_r7;
ALTER TABLE m_d8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d8 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r7 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c8 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(LN(ra.v / rb.v), 4) AS derived FROM NCAA_S.regular_season_compact_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`resilience_quotient` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_c1, m_d1, m_q1, m_m1, m_r1, m_c2, m_d2, m_q2, m_m2, m_r2, m_c3, m_d3, m_q3, m_m3, m_r3, m_c4, m_d4, m_q4, m_m4, m_r4, m_c5, m_d5, m_q5, m_m5, m_r5, m_c6, m_d6, m_q6, m_m6, m_r6, m_c7, m_d7, m_q7, m_m7, m_r7, m_c8, m_d8, m_q8, m_m8, m_r8, m_rb, m_gt;

-- NCAA_S.regular_season_detailed_results.adversity_grade: Massey on per-100-possession margin (detailed results), rating of the loser
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST((wscore - lscore) * 100.0 / NULLIF(wfga - wor + wto + 0.475 * wfta, 0), 25) AS m FROM NCAA_S.regular_season_detailed_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST((wscore - lscore) * 100.0 / NULLIF(wfga - wor + wto + 0.475 * wfta, 0), 25) AS m FROM NCAA_S.regular_season_detailed_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, AVG(v) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, AVG(v) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, AVG(v) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, AVG(v) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, AVG(v) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, AVG(v) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, AVG(v) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, AVG(v) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(rb.v, 4) AS derived FROM NCAA_S.regular_season_detailed_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_detailed_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`adversity_grade` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_q1, m_m1, m_r1, m_q2, m_m2, m_r2, m_q3, m_m3, m_r3, m_q4, m_m4, m_r4, m_q5, m_m5, m_r5, m_q6, m_m6, m_r6, m_q7, m_m7, m_r7, m_q8, m_m8, m_r8, m_rb, m_gt;

-- NCAA_S.regular_season_compact_results.pairing_edge: Colley rating per season (Jacobi, 8 steps), difference winner minus loser
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.5 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r1 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r2 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r3 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r4 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r5 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r6 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r7 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r8 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v - rb.v, 4) AS derived FROM NCAA_S.regular_season_compact_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`pairing_edge` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_r1, m_r2, m_r3, m_r4, m_r5, m_r6, m_r7, m_r8, m_rb, m_gt;

-- NCAA_S.regular_season_compact_results.latent_poise: Massey rating per season, margin capped, centred each step, 10 Jacobi steps, difference
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, AVG(v) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, AVG(v) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, AVG(v) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, AVG(v) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, AVG(v) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, AVG(v) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, AVG(v) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, AVG(v) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q9 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r8 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m9 AS SELECT grp, AVG(v) AS mu FROM m_q9 GROUP BY grp;
CREATE TEMPORARY TABLE m_r9 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q9 q JOIN m_m9 m ON m.grp = q.grp;
ALTER TABLE m_r9 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q10 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r9 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m10 AS SELECT grp, AVG(v) AS mu FROM m_q10 GROUP BY grp;
CREATE TEMPORARY TABLE m_r10 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q10 q JOIN m_m10 m ON m.grp = q.grp;
ALTER TABLE m_r10 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r10;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v - rb.v, 4) AS derived FROM NCAA_S.regular_season_compact_results s LEFT JOIN m_r10 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`latent_poise` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_q1, m_m1, m_r1, m_q2, m_m2, m_r2, m_q3, m_m3, m_r3, m_q4, m_m4, m_r4, m_q5, m_m5, m_r5, m_q6, m_m6, m_r6, m_q7, m_m7, m_r7, m_q8, m_m8, m_r8, m_q9, m_m9, m_r9, m_q10, m_m10, m_r10, m_rb, m_gt;

-- NCAA_S.tourney_compact_results.cushion_reading: regular-season Massey rating applied to tournament games, difference
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, AVG(v) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, AVG(v) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, AVG(v) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, AVG(v) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, AVG(v) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, AVG(v) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, AVG(v) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, AVG(v) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v - rb.v, 4) AS derived FROM NCAA_S.tourney_compact_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`tourney_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`cushion_reading` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_q1, m_m1, m_r1, m_q2, m_m2, m_r2, m_q3, m_m3, m_r3, m_q4, m_m4, m_r4, m_q5, m_m5, m_r5, m_q6, m_m6, m_r6, m_q7, m_m7, m_r7, m_q8, m_m8, m_r8, m_rb, m_gt;

-- NCAA_S.tourney_compact_results.disposition_score: regular-season Colley rating applied to tournament games, winner minus loser
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.5 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r1 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r2 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r3 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r4 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r5 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r6 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r7 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r8 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v - rb.v, 4) AS derived FROM NCAA_S.tourney_compact_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`tourney_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`disposition_score` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_r1, m_r2, m_r3, m_r4, m_r5, m_r6, m_r7, m_r8, m_rb, m_gt;

-- NCAA_S.tourney_compact_results.conviction_margin: regular-season Bradley-Terry strengths, winner win probability in the tournament game
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 20) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 1.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c1 AS SELECT * FROM m_r0;
ALTER TABLE m_c1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d1 AS SELECT * FROM m_r0;
ALTER TABLE m_d1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d1 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r0 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c1 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c2 AS SELECT * FROM m_r1;
ALTER TABLE m_c2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d2 AS SELECT * FROM m_r1;
ALTER TABLE m_d2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d2 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r1 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c2 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c3 AS SELECT * FROM m_r2;
ALTER TABLE m_c3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d3 AS SELECT * FROM m_r2;
ALTER TABLE m_d3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d3 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r2 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c3 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c4 AS SELECT * FROM m_r3;
ALTER TABLE m_c4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d4 AS SELECT * FROM m_r3;
ALTER TABLE m_d4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d4 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r3 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c4 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c5 AS SELECT * FROM m_r4;
ALTER TABLE m_c5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d5 AS SELECT * FROM m_r4;
ALTER TABLE m_d5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d5 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r4 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c5 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c6 AS SELECT * FROM m_r5;
ALTER TABLE m_c6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d6 AS SELECT * FROM m_r5;
ALTER TABLE m_d6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d6 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r5 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c6 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c7 AS SELECT * FROM m_r6;
ALTER TABLE m_c7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d7 AS SELECT * FROM m_r6;
ALTER TABLE m_d7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d7 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r6 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c7 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c8 AS SELECT * FROM m_r7;
ALTER TABLE m_c8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d8 AS SELECT * FROM m_r7;
ALTER TABLE m_d8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d8 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r7 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c8 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v / (ra.v + rb.v), 4) AS derived FROM NCAA_S.tourney_compact_results s LEFT JOIN m_r8 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`tourney_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`conviction_margin` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_c1, m_d1, m_q1, m_m1, m_r1, m_c2, m_d2, m_q2, m_m2, m_r2, m_c3, m_d3, m_q3, m_m3, m_r3, m_c4, m_d4, m_q4, m_m4, m_r4, m_c5, m_d5, m_q5, m_m5, m_r5, m_c6, m_d6, m_q6, m_m6, m_r6, m_c7, m_d7, m_q7, m_m7, m_r7, m_c8, m_d8, m_q8, m_m8, m_r8, m_rb, m_gt;

-- NCAA_S.regular_season_compact_results.tenor_balance: Bradley-Terry strength of the winner, 10 steps
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 15) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 15) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 1.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c1 AS SELECT * FROM m_r0;
ALTER TABLE m_c1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d1 AS SELECT * FROM m_r0;
ALTER TABLE m_d1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d1 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r0 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c1 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c2 AS SELECT * FROM m_r1;
ALTER TABLE m_c2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d2 AS SELECT * FROM m_r1;
ALTER TABLE m_d2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d2 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r1 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c2 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c3 AS SELECT * FROM m_r2;
ALTER TABLE m_c3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d3 AS SELECT * FROM m_r2;
ALTER TABLE m_d3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d3 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r2 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c3 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c4 AS SELECT * FROM m_r3;
ALTER TABLE m_c4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d4 AS SELECT * FROM m_r3;
ALTER TABLE m_d4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d4 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r3 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c4 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c5 AS SELECT * FROM m_r4;
ALTER TABLE m_c5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d5 AS SELECT * FROM m_r4;
ALTER TABLE m_d5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d5 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r4 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c5 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c6 AS SELECT * FROM m_r5;
ALTER TABLE m_c6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d6 AS SELECT * FROM m_r5;
ALTER TABLE m_d6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d6 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r5 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c6 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c7 AS SELECT * FROM m_r6;
ALTER TABLE m_c7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d7 AS SELECT * FROM m_r6;
ALTER TABLE m_d7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d7 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r6 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c7 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c8 AS SELECT * FROM m_r7;
ALTER TABLE m_c8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d8 AS SELECT * FROM m_r7;
ALTER TABLE m_d8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d8 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r7 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c8 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c9 AS SELECT * FROM m_r8;
ALTER TABLE m_c9 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d9 AS SELECT * FROM m_r8;
ALTER TABLE m_d9 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q9 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d9 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r8 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c9 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m9 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q9 GROUP BY grp;
CREATE TEMPORARY TABLE m_r9 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q9 q JOIN m_m9 m ON m.grp = q.grp;
ALTER TABLE m_r9 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c10 AS SELECT * FROM m_r9;
ALTER TABLE m_c10 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d10 AS SELECT * FROM m_r9;
ALTER TABLE m_d10 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q10 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d10 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r9 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c10 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m10 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q10 GROUP BY grp;
CREATE TEMPORARY TABLE m_r10 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q10 q JOIN m_m10 m ON m.grp = q.grp;
ALTER TABLE m_r10 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r10;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v, 4) AS derived FROM NCAA_S.regular_season_compact_results s LEFT JOIN m_r10 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`tenor_balance` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_c1, m_d1, m_q1, m_m1, m_r1, m_c2, m_d2, m_q2, m_m2, m_r2, m_c3, m_d3, m_q3, m_m3, m_r3, m_c4, m_d4, m_q4, m_m4, m_r4, m_c5, m_d5, m_q5, m_m5, m_r5, m_c6, m_d6, m_q6, m_m6, m_r6, m_c7, m_d7, m_q7, m_m7, m_r7, m_c8, m_d8, m_q8, m_m8, m_r8, m_c9, m_d9, m_q9, m_m9, m_r9, m_c10, m_d10, m_q10, m_m10, m_r10, m_rb, m_gt;

-- NCAA_S.regular_season_compact_results.strain_reading: Massey rating of the winner with margin cap 10, 6 steps
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 10) AS m FROM NCAA_S.regular_season_compact_results) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT season AS grp, wteam AS a, lteam AS b, LEAST(wscore - lscore, 10) AS m FROM NCAA_S.regular_season_compact_results) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, AVG(v) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, AVG(v) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, AVG(v) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, AVG(v) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, AVG(v) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, AVG(v) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r6;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT s.season AS k1, s.daynum AS k2, s.wteam AS k3, s.lteam AS k4, ROUND(ra.v, 4) AS derived FROM NCAA_S.regular_season_compact_results s LEFT JOIN m_r6 ra ON ra.grp = s.season AND ra.i = s.wteam LEFT JOIN m_rb rb ON rb.grp = s.season AND rb.i = s.lteam;
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN m_gt g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`strain_reading` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_q1, m_m1, m_r1, m_q2, m_m2, m_r2, m_q3, m_m3, m_r3, m_q4, m_m4, m_r4, m_q5, m_m5, m_r5, m_q6, m_m6, m_r6, m_rb, m_gt;

USE `lahman_2014_S`;

-- lahman_2014_S.appearances.allure_mass: HITS authority of the franchise over all players and years
CREATE TEMPORARY TABLE m_e AS SELECT playerID AS s, teamID AS d, 1.0 + COALESCE(G_all, 0) / 100.0 AS w FROM lahman_2014_S.appearances;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`yearID` AS k1, t.`teamID` AS k2, t.`playerID` AS k3, ROUND(q.v, 5) AS derived FROM `lahman_2014_S`.`appearances` t LEFT JOIN m_au6 q ON q.id = t.teamID;
UPDATE `lahman_2014_S`.`appearances` t JOIN m_gt g ON t.`yearID` = g.k1 AND t.`teamID` = g.k2 AND t.`playerID` = g.k3 SET t.`allure_mass` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

USE `YelpDataset3_S`;

-- helper column of Tips (surrogate row identifier, not a derived column)
SET @i := 0;
UPDATE `Tips` SET `tip_id` = (@i := @i + 1) WHERE `tip_id` IS NULL ORDER BY business_id, user_id, date_year, date_month, date_day;
ALTER TABLE `Tips` ADD UNIQUE KEY `uq_tip_id` (`tip_id`);

-- YelpDataset3_S.Reviews.voice_leverage: HITS hub score of the reviewer, star-weighted edges, 5 iterations
CREATE TEMPORARY TABLE m_e AS SELECT user_id AS s, business_id AS d, stars AS w FROM YelpDataset3_S.Reviews WHERE stars IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`review_id` AS k1, ROUND(q.v, 5) AS derived FROM `YelpDataset3_S`.`Reviews` t LEFT JOIN m_h5 q ON q.id = t.user_id;
UPDATE `YelpDataset3_S`.`Reviews` t JOIN m_gt g ON t.`review_id` = g.k1 SET t.`voice_leverage` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_gt;

-- YelpDataset3_S.Tips.draw_coefficient: HITS authority of the business on the tip graph (weights 1+likes)
CREATE TEMPORARY TABLE m_e AS SELECT user_id AS s, business_id AS d, 1.0 + likes AS w FROM YelpDataset3_S.Tips;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`tip_id` AS k1, ROUND(q.v, 5) AS derived FROM `YelpDataset3_S`.`Tips` t LEFT JOIN m_au6 q ON q.id = t.business_id;
UPDATE `YelpDataset3_S`.`Tips` t JOIN m_gt g ON t.`tip_id` = g.k1 SET t.`draw_coefficient` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

-- YelpDataset3_S.Business.endorsement_level: HITS authority of businesses on the star-weighted user-business graph, L2 normalisation, 10 iterations
CREATE TEMPORARY TABLE m_w AS SELECT user_id AS u, business_id AS b, SUM(stars) AS w FROM YelpDataset3_S.Reviews GROUP BY user_id, business_id;
ALTER TABLE m_w ADD INDEX (u), ADD INDEX (b);
CREATE TEMPORARY TABLE m_a0 (PRIMARY KEY (node)) AS SELECT DISTINCT b AS node, 1.0 AS v FROM m_w;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a0 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a1 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a1 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a2 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a2 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a3 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a3 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a4 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a4 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a5 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a5 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a6 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a6 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a7 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a7 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a8 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a8 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a9 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_hu (PRIMARY KEY (node)) AS SELECT w.u AS node, SUM(w.w * a.v) AS v FROM m_w w JOIN m_a9 a ON a.node = w.b GROUP BY w.u;
SELECT SQRT(SUM(v * v)) INTO @nh FROM m_hu;
CREATE TEMPORARY TABLE m_h (PRIMARY KEY (node)) AS SELECT node, v / @nh AS v FROM m_hu;
CREATE TEMPORARY TABLE m_au (PRIMARY KEY (node)) AS SELECT w.b AS node, SUM(w.w * h.v) AS v FROM m_w w JOIN m_h h ON h.node = w.u GROUP BY w.b;
SELECT SQRT(SUM(v * v)) INTO @na FROM m_au;
CREATE TEMPORARY TABLE m_a10 (PRIMARY KEY (node)) AS SELECT node, v / @na AS v FROM m_au;
DROP TEMPORARY TABLE m_hu;
DROP TEMPORARY TABLE m_h;
DROP TEMPORARY TABLE m_au;
CREATE TEMPORARY TABLE m_gt AS SELECT b.business_id AS k1, ROUND(a.v * 1000, 5) AS derived FROM YelpDataset3_S.Business b LEFT JOIN m_a10 a ON a.node = b.business_id;
UPDATE `YelpDataset3_S`.`Business` t JOIN m_gt g ON t.`business_id` = g.k1 SET t.`endorsement_level` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_w, m_a0, m_hu, m_h, m_au, m_a1, m_a2, m_a3, m_a4, m_a5, m_a6, m_a7, m_a8, m_a9, m_a10, m_gt;

-- YelpDataset3_S.Users.reach_quality: Katz centrality of users on the friendship graph, alpha 0.05, 8 iterations
CREATE TEMPORARY TABLE m_e AS SELECT user_id1 AS a, user_id2 AS b FROM YelpDataset3_S.Friends UNION SELECT user_id2, user_id1 FROM YelpDataset3_S.Friends;
ALTER TABLE m_e ADD INDEX (a), ADD INDEX (b);
CREATE TEMPORARY TABLE m_nn (PRIMARY KEY (node)) AS SELECT user_id AS node FROM YelpDataset3_S.Users;
CREATE TEMPORARY TABLE m_x0 (PRIMARY KEY (node)) AS SELECT node, 1.0 AS v FROM m_nn;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x0 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x1 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x1 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x2 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x2 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x3 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x3 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x4 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x4 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x5 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x5 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x6 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x6 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x7 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_in (PRIMARY KEY (node)) AS SELECT e.a AS node, SUM(x.v) AS f FROM m_e e JOIN m_x7 x ON x.node = e.b GROUP BY e.a;
CREATE TEMPORARY TABLE m_x8 (PRIMARY KEY (node)) AS SELECT nn.node, 1 + 0.05 * COALESCE(i.f, 0) AS v FROM m_nn nn LEFT JOIN m_in i ON i.node = nn.node;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_gt AS SELECT u.user_id AS k1, ROUND(x.v, 5) AS derived FROM YelpDataset3_S.Users u LEFT JOIN m_x8 x ON x.node = u.user_id;
UPDATE `YelpDataset3_S`.`Users` t JOIN m_gt g ON t.`user_id` = g.k1 SET t.`reach_quality` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_nn, m_x0, m_in, m_x1, m_x2, m_x3, m_x4, m_x5, m_x6, m_x7, m_x8, m_gt;

-- YelpDataset3_S.Reviews.engagement_wave: session number of a review within the user's history, new session after a gap of more than 45 days
CREATE TEMPORARY TABLE m_gt AS SELECT review_id AS k1, CASE WHEN user_id IS NULL THEN NULL ELSE 1 + SUM(g) OVER (PARTITION BY user_id ORDER BY review_date, review_id) END AS derived FROM (SELECT review_id, user_id, review_date, CASE WHEN DATEDIFF(review_date, LAG(review_date) OVER (PARTITION BY user_id ORDER BY review_date, review_id)) > 45 THEN 1 ELSE 0 END AS g FROM YelpDataset3_S.Reviews) x;
UPDATE `YelpDataset3_S`.`Reviews` t JOIN m_gt g ON t.`review_id` = g.k1 SET t.`engagement_wave` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

-- YelpDataset3_S.Reviews.sentiment_drift: time-decayed mean of the user's earlier review stars, half-life scale 180 days
CREATE TEMPORARY TABLE m_gt AS SELECT r.review_id AS k1, ROUND(SUM(p.stars * EXP(-DATEDIFF(r.review_date, p.review_date) / 180)) / NULLIF(SUM(EXP(-DATEDIFF(r.review_date, p.review_date) / 180)), 0), 4) AS derived FROM YelpDataset3_S.Reviews r LEFT JOIN YelpDataset3_S.Reviews p ON p.user_id = r.user_id AND p.review_date < r.review_date GROUP BY r.review_id;
UPDATE `YelpDataset3_S`.`Reviews` t JOIN m_gt g ON t.`review_id` = g.k1 SET t.`sentiment_drift` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

USE `Basketball_men_S`;

-- Basketball_men_S.players_teams.station_leverage: HITS hub score of the player on the player-team graph, minutes-weighted
CREATE TEMPORARY TABLE m_e AS SELECT playerID AS s, tmID AS d, 1.0 + COALESCE(minutes, 0) / 1000.0 AS w FROM Basketball_men_S.players_teams WHERE playerID IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`id` AS k1, ROUND(q.v, 5) AS derived FROM `Basketball_men_S`.`players_teams` t LEFT JOIN m_h6 q ON q.id = t.playerID;
UPDATE `Basketball_men_S`.`players_teams` t JOIN m_gt g ON t.`id` = g.k1 SET t.`station_leverage` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

USE `Financial_ijs_S`;

-- Financial_ijs_S.orders.destination_mass: HITS authority of the destination bank, amount-weighted
CREATE TEMPORARY TABLE m_e AS SELECT account_id AS s, bank_to AS d, amount AS w FROM Financial_ijs_S.orders WHERE bank_to IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`id` AS k1, ROUND(q.v, 5) AS derived FROM `Financial_ijs_S`.`orders` t LEFT JOIN m_au6 q ON q.id = t.bank_to;
UPDATE `Financial_ijs_S`.`orders` t JOIN m_gt g ON t.`id` = g.k1 SET t.`destination_mass` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

USE `Mondial_S`;

-- Mondial_S.country.standing_weight: personalised PageRank, length-weighted transitions, population teleport, dangling redistribution, 15 iterations
CREATE TEMPORARY TABLE m_e AS SELECT Country1 AS a, Country2 AS b, Length AS w FROM Mondial_S.borders UNION ALL SELECT Country2, Country1, Length FROM Mondial_S.borders;
CREATE TEMPORARY TABLE m_tw AS SELECT a, SUM(w) AS t FROM m_e GROUP BY a;
CREATE TEMPORARY TABLE m_pp AS SELECT Code AS node, COALESCE(Population, 0) / NULLIF((SELECT SUM(COALESCE(Population, 0)) FROM Mondial_S.country), 0) AS p FROM Mondial_S.country;
CREATE TEMPORARY TABLE m_r0 AS SELECT node, p AS rk FROM m_pp;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r0 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r0 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r1 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r1 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r2 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r2 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r3 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r3 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r4 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r4 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r5 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r5 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r6 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r6 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r7 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r7 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r8 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r8 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r9 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r9 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r9 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r10 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r10 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r10 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r11 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r11 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r11 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r12 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r12 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r12 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r13 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r13 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r13 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r14 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_dm AS SELECT COALESCE(SUM(p.rk), 0) AS m FROM m_r14 p LEFT JOIN m_tw t ON t.a = p.node WHERE t.a IS NULL;
CREATE TEMPORARY TABLE m_in AS SELECT e.b AS node, SUM(p.rk * e.w / t.t) AS f FROM m_e e JOIN m_r14 p ON p.node = e.a JOIN m_tw t ON t.a = e.a GROUP BY e.b;
CREATE TEMPORARY TABLE m_r15 AS SELECT q.node, (1 - 0.85) * q.p + 0.85 * (COALESCE(x.f, 0) + dm.m * q.p) AS rk FROM m_pp q LEFT JOIN m_in x ON x.node = q.node CROSS JOIN m_dm dm;
DROP TEMPORARY TABLE m_dm;
DROP TEMPORARY TABLE m_in;
CREATE TEMPORARY TABLE m_gt AS SELECT co.Code AS k1, ROUND(r.rk * 100, 5) AS derived FROM Mondial_S.country co JOIN m_r15 r ON r.node = co.Code;
UPDATE `Mondial_S`.`country` t JOIN m_gt g ON t.`Code` = g.k1 SET t.`standing_weight` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_tw, m_pp, m_r0, m_dm, m_in, m_r1, m_r2, m_r3, m_r4, m_r5, m_r6, m_r7, m_r8, m_r9, m_r10, m_r11, m_r12, m_r13, m_r14, m_r15, m_gt;

-- Mondial_S.isMember.affinity_mass: HITS hub score of the country over the membership bipartite graph
CREATE TEMPORARY TABLE m_e AS SELECT Country AS s, Organization AS d, CASE Type WHEN 'member' THEN 1.0 ELSE 0.5 END AS w FROM Mondial_S.isMember;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Country` AS k1, t.`Organization` AS k2, ROUND(q.v, 5) AS derived FROM `Mondial_S`.`isMember` t LEFT JOIN m_h6 q ON q.id = t.Country;
UPDATE `Mondial_S`.`isMember` t JOIN m_gt g ON t.`Country` = g.k1 AND t.`Organization` = g.k2 SET t.`affinity_mass` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

USE `stats_S`;

-- stats_S.postLinks.pull_coefficient: Katz centrality (alpha 0.05, 8 iterations) of the linked post on the post-link graph
CREATE TEMPORARY TABLE m_e AS SELECT PostId AS s, RelatedPostId AS d, CASE LinkTypeId WHEN 3 THEN 2.0 ELSE 1.0 END AS w FROM stats_S.postLinks WHERE PostId IS NOT NULL AND RelatedPostId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_n (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id FROM m_e;
INSERT IGNORE INTO m_n SELECT d FROM m_e;
CREATE TEMPORARY TABLE m_x0 (PRIMARY KEY (id)) AS SELECT id, 1.0 AS v FROM m_n;
CREATE TEMPORARY TABLE m_x1 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x0 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x2 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x1 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x3 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x2 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x4 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x3 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x5 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x4 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x6 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x5 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x7 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x6 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x8 (PRIMARY KEY (id)) AS SELECT n.id, 1 + 0.05 * COALESCE(q.v, 0) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e e JOIN m_x7 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Id` AS k1, ROUND(q.v, 5) AS derived FROM `stats_S`.`postLinks` t LEFT JOIN m_x8 q ON q.id = t.RelatedPostId;
UPDATE `stats_S`.`postLinks` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`pull_coefficient` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_n, m_x0, m_x1, m_x2, m_x3, m_x4, m_x5, m_x6, m_x7, m_x8, m_gt;

-- stats_S.postLinks.provenance_mass: HITS authority of the linked post, 6 iterations, max-normalised
CREATE TEMPORARY TABLE m_e AS SELECT PostId AS s, RelatedPostId AS d, CASE LinkTypeId WHEN 3 THEN 2.0 ELSE 1.0 END AS w FROM stats_S.postLinks WHERE PostId IS NOT NULL AND RelatedPostId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Id` AS k1, ROUND(q.v, 5) AS derived FROM `stats_S`.`postLinks` t LEFT JOIN m_au6 q ON q.id = t.RelatedPostId;
UPDATE `stats_S`.`postLinks` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`provenance_mass` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

-- stats_S.postLinks.resonance_level: clipped diffusion over the row-normalised link graph, damping 0.85, cap 3, 8 iterations
CREATE TEMPORARY TABLE m_e AS SELECT PostId AS s, RelatedPostId AS d, CASE LinkTypeId WHEN 3 THEN 2.0 ELSE 1.0 END AS w FROM stats_S.postLinks WHERE PostId IS NOT NULL AND RelatedPostId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_o AS SELECT s, SUM(w) ow FROM m_e GROUP BY s;
CREATE TEMPORARY TABLE m_e2 AS SELECT e.s, e.d, e.w / o.ow AS w FROM m_e e JOIN m_o o ON o.s = e.s;
ALTER TABLE m_e2 ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_n (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id FROM m_e;
INSERT IGNORE INTO m_n SELECT d FROM m_e;
CREATE TEMPORARY TABLE m_x0 (PRIMARY KEY (id)) AS SELECT id, 1.0 AS v FROM m_n;
CREATE TEMPORARY TABLE m_x1 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x0 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x2 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x1 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x3 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x2 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x4 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x3 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x5 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x4 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x6 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x5 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x7 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x6 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x8 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x7 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Id` AS k1, ROUND(q.v, 5) AS derived FROM `stats_S`.`postLinks` t LEFT JOIN m_x8 q ON q.id = t.RelatedPostId;
UPDATE `stats_S`.`postLinks` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`resonance_level` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_o, m_e2, m_n, m_x0, m_x1, m_x2, m_x3, m_x4, m_x5, m_x6, m_x7, m_x8, m_gt;

-- stats_S.badges.merit_stature: HITS hub score of the user on the user-badge graph
CREATE TEMPORARY TABLE m_e AS SELECT UserId AS s, Name AS d, 1.0 AS w FROM stats_S.badges WHERE UserId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Id` AS k1, ROUND(q.v, 5) AS derived FROM `stats_S`.`badges` t LEFT JOIN m_h6 q ON q.id = t.UserId;
UPDATE `stats_S`.`badges` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`merit_stature` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

-- stats_S.votes.reception_grade: HITS authority of the voted post, vote type weights, 5 iterations
CREATE TEMPORARY TABLE m_e AS SELECT UserId AS s, PostId AS d, CASE VoteTypeId WHEN 2 THEN 1.0 WHEN 3 THEN 0.25 ELSE 0.5 END AS w FROM stats_S.votes WHERE UserId IS NOT NULL AND PostId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`Id` AS k1, ROUND(q.v, 5) AS derived FROM `stats_S`.`votes` t LEFT JOIN m_au5 q ON q.id = t.PostId;
UPDATE `stats_S`.`votes` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`reception_grade` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_gt;

-- stats_S.comments.conversation_burst: session number of a comment within the user's history, new session after a gap of more than 14 days
CREATE TEMPORARY TABLE m_gt AS SELECT Id AS k1, CASE WHEN UserId IS NULL THEN NULL ELSE 1 + SUM(g) OVER (PARTITION BY UserId ORDER BY CreationDate, Id) END AS derived FROM (SELECT Id, UserId, CreationDate, CASE WHEN DATEDIFF(CreationDate, LAG(CreationDate) OVER (PARTITION BY UserId ORDER BY CreationDate, Id)) > 14 THEN 1 ELSE 0 END AS g FROM stats_S.comments) x;
UPDATE `stats_S`.`comments` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`conversation_burst` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

-- stats_S.votes.attention_flow: clipped diffusion over the user-post vote graph (both directions), damping 0.85, cap 3, 6 iterations
CREATE TEMPORARY TABLE m_e AS SELECT CONCAT('u', UserId) AS s, CONCAT('p', PostId) AS d, CASE VoteTypeId WHEN 2 THEN 1.0 WHEN 3 THEN 0.25 ELSE 0.5 END AS w FROM stats_S.votes WHERE UserId IS NOT NULL AND PostId IS NOT NULL UNION ALL SELECT CONCAT('p', PostId), CONCAT('u', UserId), CASE VoteTypeId WHEN 2 THEN 1.0 WHEN 3 THEN 0.25 ELSE 0.5 END FROM stats_S.votes WHERE UserId IS NOT NULL AND PostId IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_o AS SELECT s, SUM(w) ow FROM m_e GROUP BY s;
CREATE TEMPORARY TABLE m_e2 AS SELECT e.s, e.d, e.w / o.ow AS w FROM m_e e JOIN m_o o ON o.s = e.s;
ALTER TABLE m_e2 ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_n (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id FROM m_e;
INSERT IGNORE INTO m_n SELECT d FROM m_e;
CREATE TEMPORARY TABLE m_x0 (PRIMARY KEY (id)) AS SELECT id, 1.0 AS v FROM m_n;
CREATE TEMPORARY TABLE m_x1 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x0 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x2 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x1 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x3 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x2 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x4 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x3 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x5 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x4 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_x6 (PRIMARY KEY (id)) AS SELECT n.id, (1 - 0.85) + 0.85 * LEAST(3.0, COALESCE(q.v, 0)) AS v FROM m_n n LEFT JOIN (SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * x.v) AS v FROM m_e2 e JOIN m_x5 x ON x.id = e.s GROUP BY e.d) q ON q.id = n.id;
CREATE TEMPORARY TABLE m_gt AS SELECT t.Id AS k1, ROUND(q.v, 5) AS derived FROM stats_S.votes t LEFT JOIN m_x6 q ON q.id = CONCAT('p', t.PostId);
UPDATE `stats_S`.`votes` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`attention_flow` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_o, m_e2, m_n, m_x0, m_x1, m_x2, m_x3, m_x4, m_x5, m_x6, m_gt;

-- stats_S.posts.owner_activity_session_number: 
CREATE TEMPORARY TABLE m_gt AS WITH act AS (SELECT OwnerUserId AS uid, CreaionDate AS t, 0 AS k, Id AS rid FROM stats_S.posts WHERE OwnerUserId IS NOT NULL UNION ALL SELECT UserId, CreationDate, 1, Id FROM stats_S.comments WHERE UserId IS NOT NULL), x AS (SELECT uid, t, k, rid, CASE WHEN TIMESTAMPDIFF(DAY, LAG(t) OVER (PARTITION BY uid ORDER BY t, k, rid), t) > 30 THEN 1 ELSE 0 END AS brk FROM act), y AS (SELECT uid, k, rid, 1 + SUM(brk) OVER (PARTITION BY uid ORDER BY t, k, rid ROWS UNBOUNDED PRECEDING) AS ses FROM x) SELECT p.Id AS k1, y.ses AS derived FROM stats_S.posts p LEFT JOIN y ON y.k = 0 AND y.rid = p.Id;
UPDATE `stats_S`.`posts` t JOIN m_gt g ON t.`Id` = g.k1 SET t.`owner_activity_session_number` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

USE `imdb_full_S`;

-- imdb_full_S.movies2actors.pedigree_mass: HITS authority of the movie on the actor-movie graph, leading roles weigh 2
CREATE TEMPORARY TABLE m_e AS SELECT actorid AS s, movieid AS d, CASE WHEN `leading` > 0 THEN 2.0 ELSE 1.0 END AS w FROM imdb_full_S.movies2actors;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`movieid` AS k1, t.`actorid` AS k2, ROUND(q.v, 5) AS derived FROM `imdb_full_S`.`movies2actors` t LEFT JOIN m_au6 q ON q.id = t.movieid;
UPDATE `imdb_full_S`.`movies2actors` t JOIN m_gt g ON t.`movieid` = g.k1 AND t.`actorid` = g.k2 SET t.`pedigree_mass` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

-- imdb_full_S.movies2actors.salience_factor: HITS hub score of the actor, 5 iterations
CREATE TEMPORARY TABLE m_e AS SELECT actorid AS s, movieid AS d, CASE WHEN `leading` > 0 THEN 2.0 ELSE 1.0 END AS w FROM imdb_full_S.movies2actors;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`movieid` AS k1, t.`actorid` AS k2, ROUND(q.v, 5) AS derived FROM `imdb_full_S`.`movies2actors` t LEFT JOIN m_h5 q ON q.id = t.actorid;
UPDATE `imdb_full_S`.`movies2actors` t JOIN m_gt g ON t.`movieid` = g.k1 AND t.`actorid` = g.k2 SET t.`salience_factor` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_gt;

-- imdb_full_S.movies2directors.directing_clout: HITS authority of the director on the movie-director graph, max-normalised, 6 iterations
CREATE TEMPORARY TABLE m_e AS SELECT movieid AS s, directorid AS d, 1.0 AS w FROM imdb_full_S.movies2directors;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.movieid AS k1, t.directorid AS k2, ROUND(q.v, 5) AS derived FROM imdb_full_S.movies2directors t LEFT JOIN m_au6 q ON q.id = t.directorid;
UPDATE `imdb_full_S`.`movies2directors` t JOIN m_gt g ON t.`movieid` = g.k1 AND t.`directorid` = g.k2 SET t.`directing_clout` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;

USE `ErgastF1_S`;

-- ErgastF1_S.results.pairwise_clout: Keener rating per season (smoothed pairwise shares, skewing function, power iteration, 30 iterations), scaled by driver count
CREATE TEMPORARY TABLE m_P AS SELECT ra.year, r1.driverId AS i, r2.driverId AS j, SUM(CASE WHEN r1.positionOrder < r2.positionOrder THEN 1 ELSE 0 END) AS s FROM ErgastF1_S.results r1 JOIN ErgastF1_S.results r2 ON r2.raceId = r1.raceId AND r2.driverId <> r1.driverId JOIN ErgastF1_S.races ra ON ra.raceId = r1.raceId GROUP BY ra.year, r1.driverId, r2.driverId;
CREATE TEMPORARY TABLE m_P2 AS SELECT year, i, j, s FROM m_P;
CREATE TEMPORARY TABLE m_A AS SELECT p.year, p.i, p.j, 0.5 + SIGN((p.s + 1) / (p.s + q.s + 2) - 0.5) * SQRT(ABS(2 * (p.s + 1) / (p.s + q.s + 2) - 1)) / 2 AS a FROM m_P p JOIN m_P2 q ON q.year = p.year AND q.i = p.j AND q.j = p.i;
ALTER TABLE m_A ADD INDEX (year, j);
CREATE TEMPORARY TABLE m_x0 (PRIMARY KEY (year, node)) AS SELECT DISTINCT year, i AS node, 1.0 AS v FROM m_A;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x0 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x1 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x1 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x2 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x2 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x3 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x3 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x4 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x4 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x5 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x5 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x6 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x6 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x7 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x7 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x8 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x8 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x9 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x9 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x10 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x10 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x11 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x11 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x12 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x12 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x13 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x13 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x14 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x14 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x15 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x15 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x16 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x16 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x17 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x17 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x18 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x18 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x19 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x19 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x20 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x20 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x21 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x21 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x22 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x22 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x23 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x23 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x24 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x24 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x25 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x25 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x26 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x26 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x27 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x27 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x28 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x28 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x29 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_raw AS SELECT a.year, a.i AS node, SUM(a.a * x.v) AS v FROM m_A a JOIN m_x29 x ON x.year = a.year AND x.node = a.j GROUP BY a.year, a.i;
CREATE TEMPORARY TABLE m_x30 (PRIMARY KEY (year, node)) AS SELECT year, node, v / SUM(v) OVER (PARTITION BY year) AS v FROM m_raw;
DROP TEMPORARY TABLE m_raw;
CREATE TEMPORARY TABLE m_fin (PRIMARY KEY (year, node)) AS SELECT year, node, v * COUNT(*) OVER (PARTITION BY year) AS v FROM m_x30;
CREATE TEMPORARY TABLE m_gt AS SELECT r.resultId AS k1, ROUND(f.v, 4) AS derived FROM ErgastF1_S.results r JOIN ErgastF1_S.races ra ON ra.raceId = r.raceId LEFT JOIN m_fin f ON f.year = ra.year AND f.node = r.driverId;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`pairwise_clout` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_P, m_P2, m_A, m_x0, m_raw, m_x1, m_x2, m_x3, m_x4, m_x5, m_x6, m_x7, m_x8, m_x9, m_x10, m_x11, m_x12, m_x13, m_x14, m_x15, m_x16, m_x17, m_x18, m_x19, m_x20, m_x21, m_x22, m_x23, m_x24, m_x25, m_x26, m_x27, m_x28, m_x29, m_x30, m_fin, m_gt;

-- ErgastF1_S.results.momentum_trace: irregularly spaced EMA of field-normalised positions gained, finished races only, time half-life
CREATE TEMPORARY TABLE m_gt AS WITH RECURSIVE x AS (SELECT r.resultId, r.driverId, ra.date AS d, ra.raceId, (r.grid - r.positionOrder) / NULLIF(cnt.n, 0) AS g, CASE WHEN st.status = 'Finished' OR st.status LIKE '+%' THEN 1 ELSE 0 END AS fin FROM ErgastF1_S.results r JOIN ErgastF1_S.races ra ON ra.raceId = r.raceId JOIN ErgastF1_S.status st ON st.statusId = r.statusId JOIN (SELECT raceId, COUNT(*) AS n FROM ErgastF1_S.results GROUP BY raceId) cnt ON cnt.raceId = r.raceId), allr AS (SELECT resultId, driverId, d, raceId, fin, SUM(fin) OVER (PARTITION BY driverId ORDER BY d, raceId ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS nprev FROM x), o AS (SELECT driverId, d, g, ROW_NUMBER() OVER (PARTITION BY driverId ORDER BY d, raceId) AS rn FROM x WHERE fin = 1), e AS (SELECT driverId, rn, d, g * 1.0 AS ema FROM o WHERE rn = 1 UNION ALL SELECT o.driverId, o.rn, o.d, (1 - POW(0.5, DATEDIFF(o.d, e.d) / 365)) * o.g + POW(0.5, DATEDIFF(o.d, e.d) / 365) * e.ema FROM e JOIN o ON o.driverId = e.driverId AND o.rn = e.rn + 1) SELECT a.resultId AS k1, ROUND(e.ema, 4) AS derived FROM allr a LEFT JOIN e ON e.driverId = a.driverId AND e.rn = a.nprev;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`momentum_trace` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_gt;

-- ErgastF1_S.results.tenure_stature: Massey rating of the driver per season, place differences capped
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, AVG(v) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, AVG(v) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, AVG(v) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, AVG(v) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, AVG(v) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, AVG(v) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, AVG(v) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.s + COALESCE(x.sj, 0)) / t.n AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, AVG(v) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v - m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT t.resultId AS k1, ROUND(r.v, 4) AS derived FROM ErgastF1_S.results t JOIN ErgastF1_S.races ra ON ra.raceId = t.raceId LEFT JOIN m_r8 r ON r.grp = ra.year AND r.i = t.driverId;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`tenure_stature` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_q1, m_m1, m_r1, m_q2, m_m2, m_r2, m_q3, m_m3, m_r3, m_q4, m_m4, m_r4, m_q5, m_m5, m_r5, m_q6, m_m6, m_r6, m_q7, m_m7, m_r7, m_q8, m_m8, m_r8, m_rb, m_gt;

-- ErgastF1_S.results.lineage_grade: Colley rating of the driver per season from finishing-order pairs
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.5 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r1 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r2 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r3 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r4 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r5 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r6 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r7 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r8 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT t.resultId AS k1, ROUND(r.v, 4) AS derived FROM ErgastF1_S.results t JOIN ErgastF1_S.races ra ON ra.raceId = t.raceId LEFT JOIN m_r8 r ON r.grp = ra.year AND r.i = t.driverId;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`lineage_grade` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_r1, m_r2, m_r3, m_r4, m_r5, m_r6, m_r7, m_r8, m_rb, m_gt;

-- ErgastF1_S.results.mettle_rating: Bradley-Terry strength of the driver per season from finishing-order duels
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.positionOrder - a.positionOrder, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.positionOrder < b.positionOrder JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 1.0 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c1 AS SELECT * FROM m_r0;
ALTER TABLE m_c1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d1 AS SELECT * FROM m_r0;
ALTER TABLE m_d1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q1 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d1 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r0 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c1 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m1 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q1 GROUP BY grp;
CREATE TEMPORARY TABLE m_r1 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q1 q JOIN m_m1 m ON m.grp = q.grp;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c2 AS SELECT * FROM m_r1;
ALTER TABLE m_c2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d2 AS SELECT * FROM m_r1;
ALTER TABLE m_d2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q2 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d2 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r1 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c2 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m2 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q2 GROUP BY grp;
CREATE TEMPORARY TABLE m_r2 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q2 q JOIN m_m2 m ON m.grp = q.grp;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c3 AS SELECT * FROM m_r2;
ALTER TABLE m_c3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d3 AS SELECT * FROM m_r2;
ALTER TABLE m_d3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q3 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d3 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r2 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c3 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m3 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q3 GROUP BY grp;
CREATE TEMPORARY TABLE m_r3 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q3 q JOIN m_m3 m ON m.grp = q.grp;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c4 AS SELECT * FROM m_r3;
ALTER TABLE m_c4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d4 AS SELECT * FROM m_r3;
ALTER TABLE m_d4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q4 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d4 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r3 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c4 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m4 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q4 GROUP BY grp;
CREATE TEMPORARY TABLE m_r4 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q4 q JOIN m_m4 m ON m.grp = q.grp;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c5 AS SELECT * FROM m_r4;
ALTER TABLE m_c5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d5 AS SELECT * FROM m_r4;
ALTER TABLE m_d5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q5 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d5 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r4 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c5 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m5 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q5 GROUP BY grp;
CREATE TEMPORARY TABLE m_r5 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q5 q JOIN m_m5 m ON m.grp = q.grp;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c6 AS SELECT * FROM m_r5;
ALTER TABLE m_c6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d6 AS SELECT * FROM m_r5;
ALTER TABLE m_d6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q6 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d6 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r5 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c6 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m6 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q6 GROUP BY grp;
CREATE TEMPORARY TABLE m_r6 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q6 q JOIN m_m6 m ON m.grp = q.grp;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c7 AS SELECT * FROM m_r6;
ALTER TABLE m_c7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d7 AS SELECT * FROM m_r6;
ALTER TABLE m_d7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q7 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d7 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r6 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c7 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m7 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q7 GROUP BY grp;
CREATE TEMPORARY TABLE m_r7 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q7 q JOIN m_m7 m ON m.grp = q.grp;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_c8 AS SELECT * FROM m_r7;
ALTER TABLE m_c8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_d8 AS SELECT * FROM m_r7;
ALTER TABLE m_d8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_q8 AS SELECT t.grp, t.i, (t.w + 0.5) / (COALESCE(x.d, 0) + 1 / (1 + pi.v)) AS v FROM m_tt t JOIN m_d8 pi ON pi.grp = t.grp AND pi.i = t.i LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n / (a.v + b.v)) AS d FROM m_nn nn JOIN m_r7 a ON a.grp = nn.grp AND a.i = nn.i JOIN m_c8 b ON b.grp = nn.grp AND b.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
CREATE TEMPORARY TABLE m_m8 AS SELECT grp, EXP(AVG(LN(v))) AS mu FROM m_q8 GROUP BY grp;
CREATE TEMPORARY TABLE m_r8 AS SELECT q.grp, q.i, q.v / m.mu AS v FROM m_q8 q JOIN m_m8 m ON m.grp = q.grp;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT t.resultId AS k1, ROUND(r.v, 4) AS derived FROM ErgastF1_S.results t JOIN ErgastF1_S.races ra ON ra.raceId = t.raceId LEFT JOIN m_r8 r ON r.grp = ra.year AND r.i = t.driverId;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`mettle_rating` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_c1, m_d1, m_q1, m_m1, m_r1, m_c2, m_d2, m_q2, m_m2, m_r2, m_c3, m_d3, m_q3, m_m3, m_r3, m_c4, m_d4, m_q4, m_m4, m_r4, m_c5, m_d5, m_q5, m_m5, m_r5, m_c6, m_d6, m_q6, m_m6, m_r6, m_c7, m_d7, m_q7, m_m7, m_r7, m_c8, m_d8, m_q8, m_m8, m_r8, m_rb, m_gt;

-- ErgastF1_S.results.provenance_grade: Colley rating of the driver per season from starting-grid pairs
CREATE TEMPORARY TABLE m_nn0 AS SELECT grp, a AS i, b AS j, 1 AS n, m AS s, 1 AS w FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.grid - a.grid, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.grid > 0 AND b.grid > 0 AND a.grid < b.grid JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q1 UNION ALL SELECT grp, b, a, 1, -m, 0 FROM (SELECT ra.year AS grp, a.driverId AS a, b.driverId AS b, LEAST(b.grid - a.grid, 10) AS m FROM ErgastF1_S.results a JOIN ErgastF1_S.results b ON a.raceId = b.raceId AND a.grid > 0 AND b.grid > 0 AND a.grid < b.grid JOIN ErgastF1_S.races ra ON ra.raceId = a.raceId) q2;
CREATE TEMPORARY TABLE m_nn AS SELECT grp, i, j, SUM(n) AS n, SUM(s) AS s, SUM(w) AS w FROM m_nn0 GROUP BY grp, i, j;
ALTER TABLE m_nn ADD INDEX (grp, i), ADD INDEX (grp, j);
CREATE TEMPORARY TABLE m_tt AS SELECT grp, i, SUM(n) AS n, SUM(w) AS w, SUM(s) AS s FROM m_nn GROUP BY grp, i;
ALTER TABLE m_tt ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r0 AS SELECT grp, i, 0.5 AS v FROM m_tt;
ALTER TABLE m_r0 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r1 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r0 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r1 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r2 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r1 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r2 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r3 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r2 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r3 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r4 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r3 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r4 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r5 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r4 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r5 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r6 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r5 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r6 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r7 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r6 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r7 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_r8 AS SELECT t.grp, t.i, (1 + (t.w - (t.n - t.w)) / 2 + COALESCE(x.sj, 0)) / (2 + t.n) AS v FROM m_tt t LEFT JOIN (SELECT STRAIGHT_JOIN nn.grp, nn.i, SUM(nn.n * r.v) AS sj FROM m_nn nn JOIN m_r7 r ON r.grp = nn.grp AND r.i = nn.j GROUP BY nn.grp, nn.i) x ON x.grp = t.grp AND x.i = t.i;
ALTER TABLE m_r8 ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_rb AS SELECT * FROM m_r8;
ALTER TABLE m_rb ADD INDEX (grp, i);
CREATE TEMPORARY TABLE m_gt AS SELECT t.resultId AS k1, ROUND(r.v, 4) AS derived FROM ErgastF1_S.results t JOIN ErgastF1_S.races ra ON ra.raceId = t.raceId LEFT JOIN m_r8 r ON r.grp = ra.year AND r.i = t.driverId;
UPDATE `ErgastF1_S`.`results` t JOIN m_gt g ON t.`resultId` = g.k1 SET t.`provenance_grade` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_nn0, m_nn, m_tt, m_r0, m_r1, m_r2, m_r3, m_r4, m_r5, m_r6, m_r7, m_r8, m_rb, m_gt;

USE `oulad_S`;

-- oulad_S.studentAssessment.momentum_grade: HITS hub score of the student on the student-assessment graph
CREATE TEMPORARY TABLE m_e AS SELECT id_student AS s, id_assessment AS d, 1.0 + score / 100.0 AS w FROM oulad_S.studentAssessment WHERE score IS NOT NULL;
ALTER TABLE m_e ADD INDEX (s), ADD INDEX (d);
CREATE TEMPORARY TABLE m_h0 (PRIMARY KEY (id)) AS SELECT DISTINCT s AS id, 1.0 AS v FROM m_e;
CREATE TEMPORARY TABLE m_ar1 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h0 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar1;
CREATE TEMPORARY TABLE m_au1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar1;
CREATE TEMPORARY TABLE m_hr1 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au1 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr1;
CREATE TEMPORARY TABLE m_h1 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr1;
CREATE TEMPORARY TABLE m_ar2 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h1 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar2;
CREATE TEMPORARY TABLE m_au2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar2;
CREATE TEMPORARY TABLE m_hr2 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au2 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr2;
CREATE TEMPORARY TABLE m_h2 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr2;
CREATE TEMPORARY TABLE m_ar3 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h2 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar3;
CREATE TEMPORARY TABLE m_au3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar3;
CREATE TEMPORARY TABLE m_hr3 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au3 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr3;
CREATE TEMPORARY TABLE m_h3 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr3;
CREATE TEMPORARY TABLE m_ar4 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h3 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar4;
CREATE TEMPORARY TABLE m_au4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar4;
CREATE TEMPORARY TABLE m_hr4 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au4 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr4;
CREATE TEMPORARY TABLE m_h4 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr4;
CREATE TEMPORARY TABLE m_ar5 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h4 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar5;
CREATE TEMPORARY TABLE m_au5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar5;
CREATE TEMPORARY TABLE m_hr5 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au5 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr5;
CREATE TEMPORARY TABLE m_h5 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr5;
CREATE TEMPORARY TABLE m_ar6 AS SELECT STRAIGHT_JOIN e.d AS id, SUM(e.w * h.v) AS v FROM m_e e JOIN m_h5 h ON h.id = e.s GROUP BY e.d;
SELECT MAX(v) INTO @m FROM m_ar6;
CREATE TEMPORARY TABLE m_au6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_ar6;
CREATE TEMPORARY TABLE m_hr6 AS SELECT STRAIGHT_JOIN e.s AS id, SUM(e.w * a.v) AS v FROM m_e e JOIN m_au6 a ON a.id = e.d GROUP BY e.s;
SELECT MAX(v) INTO @m FROM m_hr6;
CREATE TEMPORARY TABLE m_h6 (PRIMARY KEY (id)) AS SELECT id, v / @m AS v FROM m_hr6;
CREATE TEMPORARY TABLE m_gt AS SELECT t.`id_assessment` AS k1, t.`id_student` AS k2, ROUND(q.v, 5) AS derived FROM `oulad_S`.`studentAssessment` t LEFT JOIN m_h6 q ON q.id = t.id_student;
UPDATE `oulad_S`.`studentAssessment` t JOIN m_gt g ON t.`id_assessment` = g.k1 AND t.`id_student` = g.k2 SET t.`momentum_grade` = g.derived;
DROP TEMPORARY TABLE IF EXISTS m_e, m_h0, m_ar1, m_au1, m_hr1, m_h1, m_ar2, m_au2, m_hr2, m_h2, m_ar3, m_au3, m_hr3, m_h3, m_ar4, m_au4, m_hr4, m_h4, m_ar5, m_au5, m_hr5, m_h5, m_ar6, m_au6, m_hr6, m_h6, m_gt;


-- Part 3: the 21 added columns

USE `NCAA_S`;

-- NCAA_S.regular_season_compact_results.scoring_environment: Scoring environment of a game by combined points: defensive battle below 110, typical below 160, otherwise shootout
UPDATE `NCAA_S`.`regular_season_compact_results` t JOIN (SELECT t.season AS k1, t.daynum AS k2, t.wteam AS k3, t.lteam AS k4, CASE WHEN (t.wscore + t.lscore) IS NULL THEN NULL WHEN (t.wscore + t.lscore) < 110 THEN 'Defensive battle' WHEN (t.wscore + t.lscore) < 160 THEN 'Typical game' ELSE 'Shootout' END AS derived FROM NCAA_S.regular_season_compact_results t) g ON t.`season` = g.k1 AND t.`daynum` = g.k2 AND t.`wteam` = g.k3 AND t.`lteam` = g.k4 SET t.`scoring_environment` = g.derived;

USE `lahman_2014_S`;

-- lahman_2014_S.awardsshareplayers.vote_share_class: Vote-share class of an award candidate by points won over points possible: vote getter below 10%, contender below 50%, otherwise top contender
UPDATE `lahman_2014_S`.`awardsshareplayers` t JOIN (SELECT t.awardID AS k1, t.yearID AS k2, t.lgID AS k3, t.playerID AS k4, CASE WHEN (t.pointsWon * 1.0 / NULLIF(t.pointsMax, 0)) IS NULL THEN NULL WHEN (t.pointsWon * 1.0 / NULLIF(t.pointsMax, 0)) < 0.1 THEN 'Vote getter' WHEN (t.pointsWon * 1.0 / NULLIF(t.pointsMax, 0)) < 0.5 THEN 'Contender' ELSE 'Top contender' END AS derived FROM lahman_2014_S.awardsshareplayers t) g ON t.`awardID` = g.k1 AND t.`yearID` = g.k2 AND t.`lgID` = g.k3 AND t.`playerID` = g.k4 SET t.`vote_share_class` = g.derived;

-- lahman_2014_S.salaries.contract_era: Era of a salary record by year: pre-boom before 1990, boom years before 1998, escalation years before 2005, otherwise modern
UPDATE `lahman_2014_S`.`salaries` t JOIN (SELECT t.yearID AS k1, t.teamID AS k2, t.lgID AS k3, t.playerID AS k4, CASE WHEN t.yearID IS NULL THEN NULL WHEN t.yearID < 1990 THEN 'Pre-boom contract' WHEN t.yearID < 1998 THEN 'Boom-years contract' WHEN t.yearID < 2005 THEN 'Escalation-years contract' ELSE 'Modern contract' END AS derived FROM lahman_2014_S.salaries t) g ON t.`yearID` = g.k1 AND t.`teamID` = g.k2 AND t.`lgID` = g.k3 AND t.`playerID` = g.k4 SET t.`contract_era` = g.derived;

USE `YelpDataset3_S`;

-- YelpDataset3_S.Users.member_vintage_class: Vintage class of a reviewer by the year he joined: early adopter before 2008, established member up to 2010, otherwise newcomer
UPDATE `YelpDataset3_S`.`Users` t JOIN (SELECT u.user_id AS k1, CASE WHEN u.yelping_since_year IS NULL THEN NULL WHEN u.yelping_since_year < 2008 THEN 'Early adopter' WHEN u.yelping_since_year <= 2010 THEN 'Established member' ELSE 'Newcomer' END AS derived FROM YelpDataset3_S.Users u) g ON t.`user_id` = g.k1 SET t.`member_vintage_class` = g.derived;

-- YelpDataset3_S.Users.review_volume_class: Volume class of a reviewer by number of reviews: casual below 7, active below 40, prolific below 250, otherwise power reviewer
UPDATE `YelpDataset3_S`.`Users` t JOIN (SELECT t.user_id AS k1, CASE WHEN t.review_count IS NULL THEN NULL WHEN t.review_count < 7 THEN 'Casual reviewer' WHEN t.review_count < 40 THEN 'Active reviewer' WHEN t.review_count < 250 THEN 'Prolific reviewer' ELSE 'Power reviewer' END AS derived FROM YelpDataset3_S.Users t) g ON t.`user_id` = g.k1 SET t.`review_volume_class` = g.derived;

-- YelpDataset3_S.Users.rating_style_label: Rating style of a reviewer by average stars: tough critic below 3.2, balanced below 4.1, otherwise generous
UPDATE `YelpDataset3_S`.`Users` t JOIN (SELECT t.user_id AS k1, CASE WHEN t.average_stars IS NULL THEN NULL WHEN t.average_stars < 3.2 THEN 'Tough critic' WHEN t.average_stars < 4.1 THEN 'Balanced rater' ELSE 'Generous rater' END AS derived FROM YelpDataset3_S.Users t) g ON t.`user_id` = g.k1 SET t.`rating_style_label` = g.derived;

USE `Basketball_men_S`;

-- Basketball_men_S.players.height_class: Size class of a player by height in inches: guard-sized below 73, wing-sized below 80, otherwise big-man sized
UPDATE `Basketball_men_S`.`players` t JOIN (SELECT t.playerID AS k1, CASE WHEN t.height IS NULL THEN NULL WHEN t.height < 73 THEN 'Guard-sized' WHEN t.height < 80 THEN 'Wing-sized' ELSE 'Big-man sized' END AS derived FROM Basketball_men_S.players t) g ON t.`playerID` = g.k1 SET t.`height_class` = g.derived;

-- Basketball_men_S.coaches.coach_season_class: Class of a coaching stint by wins: rebuilding below 25, competitive below 45, otherwise contender
UPDATE `Basketball_men_S`.`coaches` t JOIN (SELECT t.coachID AS k1, t.year AS k2, t.tmID AS k3, t.stint AS k4, CASE WHEN t.won IS NULL THEN NULL WHEN t.won < 25 THEN 'Rebuilding' WHEN t.won < 45 THEN 'Competitive' ELSE 'Contender' END AS derived FROM Basketball_men_S.coaches t) g ON t.`coachID` = g.k1 AND t.`year` = g.k2 AND t.`tmID` = g.k3 AND t.`stint` = g.k4 SET t.`coach_season_class` = g.derived;

USE `Financial_ijs_S`;

-- Financial_ijs_S.accounts.account_vintage_era: Cohort of the account by opening year: founding (up to 1993), growth (1994-1995) or late (1996 and later)
UPDATE `Financial_ijs_S`.`accounts` t JOIN (SELECT a.id AS k1, CASE WHEN a.date IS NULL THEN NULL WHEN YEAR(a.date) <= 1993 THEN 'Founding cohort' WHEN YEAR(a.date) <= 1995 THEN 'Growth cohort' ELSE 'Late cohort' END AS derived FROM Financial_ijs_S.accounts a) g ON t.`id` = g.k1 SET t.`account_vintage_era` = g.derived;

-- Financial_ijs_S.cards.card_tier_label: Marketing tier of a payment card decoded from the card type: junior = youth, classic = standard, gold = premium
UPDATE `Financial_ijs_S`.`cards` t JOIN (SELECT c.id AS k1, CASE TRIM(c.type) WHEN 'junior' THEN 'Youth tier' WHEN 'classic' THEN 'Standard tier' WHEN 'gold' THEN 'Premium tier' ELSE NULL END AS derived FROM Financial_ijs_S.cards c) g ON t.`id` = g.k1 SET t.`card_tier_label` = g.derived;

-- Financial_ijs_S.districts.district_size_class: Size class of a district by inhabitants: small below 85,000, medium below 160,000, large below 480,000, otherwise metropolitan
UPDATE `Financial_ijs_S`.`districts` t JOIN (SELECT t.id AS k1, CASE WHEN t.A4 IS NULL THEN NULL WHEN t.A4 < 85000 THEN 'Small district' WHEN t.A4 < 160000 THEN 'Medium district' WHEN t.A4 < 480000 THEN 'Large district' ELSE 'Metropolitan district' END AS derived FROM Financial_ijs_S.districts t) g ON t.`id` = g.k1 SET t.`district_size_class` = g.derived;

USE `Mondial_S`;

-- Mondial_S.country.country_size_class: Size class of a country by area in square kilometres: microstate below 500, small below 60,000, medium below 700,000, otherwise large
UPDATE `Mondial_S`.`country` t JOIN (SELECT t.Code AS k1, CASE WHEN t.Area IS NULL THEN NULL WHEN t.Area < 500 THEN 'Microstate' WHEN t.Area < 60000 THEN 'Small country' WHEN t.Area < 700000 THEN 'Medium country' ELSE 'Large country' END AS derived FROM Mondial_S.country t) g ON t.`Code` = g.k1 SET t.`country_size_class` = g.derived;

-- Mondial_S.country.population_class: Population class of a country: tiny below 900,000, small below 8 million, medium below 60 million, otherwise giant
UPDATE `Mondial_S`.`country` t JOIN (SELECT t.Code AS k1, CASE WHEN t.Population IS NULL THEN NULL WHEN t.Population < 900000 THEN 'Tiny population' WHEN t.Population < 8000000 THEN 'Small population' WHEN t.Population < 60000000 THEN 'Medium population' ELSE 'Giant population' END AS derived FROM Mondial_S.country t) g ON t.`Code` = g.k1 SET t.`population_class` = g.derived;

USE `stats_S`;

-- stats_S.users.reputation_class: Reputation class of a user: newcomer below 50, contributor below 800, trusted below 6,000, otherwise expert
UPDATE `stats_S`.`users` t JOIN (SELECT t.Id AS k1, CASE WHEN t.Reputation IS NULL THEN NULL WHEN t.Reputation < 50 THEN 'Newcomer' WHEN t.Reputation < 800 THEN 'Contributor' WHEN t.Reputation < 6000 THEN 'Trusted user' ELSE 'Expert' END AS derived FROM stats_S.users t) g ON t.`Id` = g.k1 SET t.`reputation_class` = g.derived;

-- stats_S.badges.badge_period: Period in which a badge was earned: early community before 2012, growth years before 2014, otherwise mature community
UPDATE `stats_S`.`badges` t JOIN (SELECT t.Id AS k1, CASE WHEN YEAR(t.Date) IS NULL THEN NULL WHEN YEAR(t.Date) < 2012 THEN 'Early-community badge' WHEN YEAR(t.Date) < 2014 THEN 'Growth-years badge' ELSE 'Mature-community badge' END AS derived FROM stats_S.badges t) g ON t.`Id` = g.k1 SET t.`badge_period` = g.derived;

USE `imdb_full_S`;

-- imdb_full_S.movies2actors.billing_label: Billing of an actor in a film from the leading rank: unbilled when 0, top billed up to 3, otherwise supporting cast
UPDATE `imdb_full_S`.`movies2actors` t JOIN (SELECT x.movieid AS k1, x.actorid AS k2, CASE WHEN x.`leading` IS NULL THEN NULL WHEN x.`leading` = 0 THEN 'Unbilled' WHEN x.`leading` <= 3 THEN 'Top billed' ELSE 'Supporting cast' END AS derived FROM imdb_full_S.movies2actors x) g ON t.`movieid` = g.k1 AND t.`actorid` = g.k2 SET t.`billing_label` = g.derived;

USE `ErgastF1_S`;

-- ErgastF1_S.races.season_stage: Stage of the championship by round: opening stretch up to round 5, mid-season up to round 12, otherwise closing stretch
UPDATE `ErgastF1_S`.`races` t JOIN (SELECT t.raceId AS k1, CASE WHEN t.round IS NULL THEN NULL WHEN t.round < 6 THEN 'Opening stretch' WHEN t.round < 13 THEN 'Mid-season' ELSE 'Closing stretch' END AS derived FROM ErgastF1_S.races t) g ON t.`raceId` = g.k1 SET t.`season_stage` = g.derived;

-- ErgastF1_S.results.points_class: Class of a race result by points: pointless at 0, minor below 3, podium-level below 9, otherwise win-level
UPDATE `ErgastF1_S`.`results` t JOIN (SELECT t.resultId AS k1, CASE WHEN t.points IS NULL THEN NULL WHEN t.points < 0.5 THEN 'Pointless result' WHEN t.points < 3 THEN 'Minor points' WHEN t.points < 9 THEN 'Podium-level points' ELSE 'Win-level points' END AS derived FROM ErgastF1_S.results t) g ON t.`resultId` = g.k1 SET t.`points_class` = g.derived;

USE `oulad_S`;

-- oulad_S.studentInfo.course_run_class: Class of the course presentation the student is enrolled in by its length: short below 250 days, standard up to 262, otherwise long
UPDATE `oulad_S`.`studentInfo` t JOIN (SELECT si.id_student AS k1, si.code_module AS k2, si.code_presentation AS k3, CASE WHEN c.length IS NULL THEN NULL WHEN c.length < 250 THEN 'Short run' WHEN c.length <= 262 THEN 'Standard run' ELSE 'Long run' END AS derived FROM oulad_S.studentInfo si LEFT JOIN oulad_S.courses c ON c.code_module = si.code_module AND c.code_presentation = si.code_presentation) g ON t.`id_student` = g.k1 AND t.`code_module` = g.k2 AND t.`code_presentation` = g.k3 SET t.`course_run_class` = g.derived;

-- oulad_S.studentInfo.credit_load_label: Study load of the enrolment by studied credits: light below 45, standard below 75, heavy below 130, otherwise overload
UPDATE `oulad_S`.`studentInfo` t JOIN (SELECT t.id_student AS k1, t.code_module AS k2, t.code_presentation AS k3, CASE WHEN t.studied_credits IS NULL THEN NULL WHEN t.studied_credits < 45 THEN 'Light load' WHEN t.studied_credits < 75 THEN 'Standard load' WHEN t.studied_credits < 130 THEN 'Heavy load' ELSE 'Overload' END AS derived FROM oulad_S.studentInfo t) g ON t.`id_student` = g.k1 AND t.`code_module` = g.k2 AND t.`code_presentation` = g.k3 SET t.`credit_load_label` = g.derived;

-- oulad_S.assessments.assessment_stage: Stage of the course in which an assessment falls by its due day: early below 60, mid-course below 150, otherwise late
UPDATE `oulad_S`.`assessments` t JOIN (SELECT t.id_assessment AS k1, CASE WHEN t.date IS NULL THEN NULL WHEN t.date < 60 THEN 'Early assessment' WHEN t.date < 150 THEN 'Mid-course assessment' ELSE 'Late assessment' END AS derived FROM oulad_S.assessments t) g ON t.`id_assessment` = g.k1 SET t.`assessment_stage` = g.derived;

