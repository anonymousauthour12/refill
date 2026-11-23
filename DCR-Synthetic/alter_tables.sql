-- alter_tables.sql
--
-- Adds the 185 derived columns of DCR-Synthetic (all NULL) to the *_S copies of the databases.
-- Run it before populate_values.sql.
--
-- The _S databases must be plain copies of the originals, for example
--   mysqldump Mondial | mysql Mondial_S
-- and none of the columns may exist yet, otherwise MySQL stops with error 1060 (duplicate column).
--
-- sql_mode is relaxed because a few tables contain zero dates ('0000-00-00').
-- YelpDataset3_S.Tips has no key, so a helper column tip_id is added (it is not one of the 185).
-- It is filled in populate_values.sql and used by the formula of Tips.draw_coefficient.


SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION';

-- ------------------------------------------------------------
-- NCAA_S  (17 derived columns)
-- ------------------------------------------------------------
USE `NCAA_S`;

-- regular_season_detailed_results
ALTER TABLE `regular_season_detailed_results` ADD COLUMN `score_diff` INT;  -- Margin of victory: winning score minus losing score
ALTER TABLE `regular_season_detailed_results` ADD COLUMN `game_type` VARCHAR(20);  -- Game type: Overtime if numot > 0 else Regulation
ALTER TABLE `regular_season_detailed_results` ADD COLUMN `matchup_label` VARCHAR(100);  -- Matchup label: winning team vs losing team name
ALTER TABLE `regular_season_detailed_results` ADD COLUMN `adversity_grade` DECIMAL(12,4);  -- Massey on per-100-possession margin (detailed results), rating of the loser

-- tourney_seeds
ALTER TABLE `tourney_seeds` ADD COLUMN `seed_region_code` CHAR(1);  -- Tournament bracket region: first character of seed string
ALTER TABLE `tourney_seeds` ADD COLUMN `seed_number` TINYINT UNSIGNED;  -- Numeric seed rank: characters 2-3 of seed string cast to UNSIGNED

-- regular_season_compact_results
ALTER TABLE `regular_season_compact_results` ADD COLUMN `power_gap` DECIMAL(12,3);  -- SRS with cap, home-court adjustment, time decay, 10 centred iterations
ALTER TABLE `regular_season_compact_results` ADD COLUMN `strength_balance` DECIMAL(12,4);  -- Offense-Defense rating (alternating matrix scaling), defence normalised each step, 10 iterations, log ratio of overall ratings
ALTER TABLE `regular_season_compact_results` ADD COLUMN `resilience_quotient` DECIMAL(12,4);  -- Bradley-Terry MM, 8 steps, pseudo-game against a unit opponent, geometric-mean normalised per season, log ratio
ALTER TABLE `regular_season_compact_results` ADD COLUMN `pairing_edge` DECIMAL(12,4);  -- Colley rating per season (Jacobi, 8 steps), difference winner minus loser
ALTER TABLE `regular_season_compact_results` ADD COLUMN `latent_poise` DECIMAL(12,4);  -- Massey rating per season, margin capped, centred each step, 10 Jacobi steps, difference
ALTER TABLE `regular_season_compact_results` ADD COLUMN `tenor_balance` DECIMAL(12,4);  -- Bradley-Terry strength of the winner, 10 steps
ALTER TABLE `regular_season_compact_results` ADD COLUMN `strain_reading` DECIMAL(12,4);  -- Massey rating of the winner with margin cap 10, 6 steps
ALTER TABLE `regular_season_compact_results` ADD COLUMN `scoring_environment` VARCHAR(64);  -- Scoring environment of a game by combined points: defensive battle below 110, typical below 160, otherwise shootout

-- tourney_compact_results
ALTER TABLE `tourney_compact_results` ADD COLUMN `cushion_reading` DECIMAL(12,4);  -- regular-season Massey rating applied to tournament games, difference
ALTER TABLE `tourney_compact_results` ADD COLUMN `disposition_score` DECIMAL(12,4);  -- regular-season Colley rating applied to tournament games, winner minus loser
ALTER TABLE `tourney_compact_results` ADD COLUMN `conviction_margin` DECIMAL(12,4);  -- regular-season Bradley-Terry strengths, winner win probability in the tournament game

-- ------------------------------------------------------------
-- lahman_2014_S  (25 derived columns)
-- ------------------------------------------------------------
USE `lahman_2014_S`;

-- seriespost
ALTER TABLE `seriespost` ADD COLUMN `total_games` INT;  -- Total playoff series games played: wins plus losses

-- batting
ALTER TABLE `batting` ADD COLUMN `total_bases` INT;  -- Total bases: singles + 2*doubles + 3*triples + 4*home-runs
ALTER TABLE `batting` ADD COLUMN `batting_avg_change` DECIMAL(7,3);  -- Change in batting average between consecutive stints in the same seaso
ALTER TABLE `batting` ADD COLUMN `player_birth_country` VARCHAR(50);  -- Country of birth copied from players into batting
ALTER TABLE `batting` ADD COLUMN `team_win_pct` DECIMAL(6,3);  -- Win percentage of the team this batter played for in the given season
ALTER TABLE `batting` ADD COLUMN `batter_handedness` VARCHAR(10);  -- Batting handedness decoded from single-letter bats code
ALTER TABLE `batting` ADD COLUMN `player_team_label` VARCHAR(100);  -- Player and team label: lastName (teamName)
ALTER TABLE `batting` ADD COLUMN `hr_rank_in_season` INT;  -- Home run rank among all batting records in the same season (RANK)
ALTER TABLE `batting` ADD COLUMN `cumulative_career_hr` INT;  -- Cumulative career home runs up to and including this batting record

-- pitching
ALTER TABLE `pitching` ADD COLUMN `innings_pitched` DECIMAL(6,1);  -- Innings pitched: IPouts / 3 (each inning = 3 outs)
ALTER TABLE `pitching` ADD COLUMN `strikeout_rate` DECIMAL(6,2);  -- Strikeout rate (decoy): stored as K/9, not K/BFP

-- teams
ALTER TABLE `teams` ADD COLUMN `pythag_win_pct` DECIMAL(6,3);  -- Pythagorean win expectancy: R^2 / (R^2 + RA^2)
ALTER TABLE `teams` ADD COLUMN `season_result` VARCHAR(30);  -- Season result: World Series winner down to No Playoff
ALTER TABLE `teams` ADD COLUMN `win_pct` DECIMAL(6,3);  -- Win pct (decoy): stored as Pythagorean R^2/(R^2+RA^2), not W/G
ALTER TABLE `teams` ADD COLUMN `wins_improvement` INT;  -- Team wins improvement from the last recorded season
ALTER TABLE `teams` ADD COLUMN `total_payroll` BIGINT;  -- Total salary payroll for all players on the team in a given season

-- players
ALTER TABLE `players` ADD COLUMN `bmi` DECIMAL(5,1);  -- BMI (imperial): 703 * weight / height^2
ALTER TABLE `players` ADD COLUMN `full_name` VARCHAR(100);  -- Player full name: COALESCE(nameFirst,'') + space + nameLast
ALTER TABLE `players` ADD COLUMN `preferred_name` VARCHAR(50);  -- Player preferred name: COALESCE(nameNick, nameFirst)
ALTER TABLE `players` ADD COLUMN `career_hr_best_season` INT;  -- Highest home runs in any single season of this player's career

-- salaries
ALTER TABLE `salaries` ADD COLUMN `salary_change` INT;  -- Salary change from the last recorded contract year on the same team
ALTER TABLE `salaries` ADD COLUMN `contract_era` VARCHAR(64);  -- Era of a salary record by year: pre-boom before 1990, boom years before 1998, escalation years before 2005, otherwise modern

-- schools
ALTER TABLE `schools` ADD COLUMN `alumni_career_batting_games` INT;  -- Total career batting games by all alumni of this college

-- appearances
ALTER TABLE `appearances` ADD COLUMN `allure_mass` DECIMAL(12,5);  -- HITS authority of the franchise over all players and years

-- awardsshareplayers
ALTER TABLE `awardsshareplayers` ADD COLUMN `vote_share_class` VARCHAR(64);  -- Vote-share class of an award candidate by points won over points possible: vote getter below 10%, contender below 50%, otherwise top contend

-- ------------------------------------------------------------
-- YelpDataset3_S  (15 derived columns)
-- ------------------------------------------------------------
USE `YelpDataset3_S`;

-- helper column (not a derived column)
ALTER TABLE `Tips` ADD COLUMN `tip_id` BIGINT NULL;  -- surrogate row identifier

-- Reviews
ALTER TABLE `Reviews` ADD COLUMN `votes_total` INT;  -- Total engagement votes: funny + useful + cool
ALTER TABLE `Reviews` ADD COLUMN `sentiment` VARCHAR(20);  -- Review sentiment: Positive / Neutral / Negative from star rating
ALTER TABLE `Reviews` ADD COLUMN `user_review_sequence` BIGINT;  -- Sequential review number for this reviewer (ROW_NUMBER by date, id)
ALTER TABLE `Reviews` ADD COLUMN `voice_leverage` DECIMAL(12,5);  -- HITS hub score of the reviewer, star-weighted edges, 5 iterations
ALTER TABLE `Reviews` ADD COLUMN `engagement_wave` INT;  -- session number of a review within the user's history, new session after a gap of more than 45 days
ALTER TABLE `Reviews` ADD COLUMN `sentiment_drift` DECIMAL(12,4);  -- time-decayed mean of the user's earlier review stars, half-life scale 180 days

-- Business
ALTER TABLE `Business` ADD COLUMN `city_state` VARCHAR(100);  -- Business location: city + ', ' + state
ALTER TABLE `Business` ADD COLUMN `avg_useful_votes` DECIMAL(8,2);  -- Average useful votes per review for this business
ALTER TABLE `Business` ADD COLUMN `positive_reviews` INT;  -- Number of reviews with 4+ stars for this business
ALTER TABLE `Business` ADD COLUMN `endorsement_level` DECIMAL(12,5);  -- HITS authority of businesses on the star-weighted user-business graph, L2 normalisation, 10 iterations

-- Tips
ALTER TABLE `Tips` ADD COLUMN `draw_coefficient` DECIMAL(12,5);  -- HITS authority of the business on the tip graph (weights 1+likes)

-- Users
ALTER TABLE `Users` ADD COLUMN `reach_quality` DECIMAL(15,5);  -- Katz centrality of users on the friendship graph, alpha 0.05, 8 iterations
ALTER TABLE `Users` ADD COLUMN `member_vintage_class` VARCHAR(64);  -- Vintage class of a reviewer by the year he joined: early adopter before 2008, established member up to 2010, otherwise newcomer
ALTER TABLE `Users` ADD COLUMN `review_volume_class` VARCHAR(64);  -- Volume class of a reviewer by number of reviews: casual below 7, active below 40, prolific below 250, otherwise power reviewer
ALTER TABLE `Users` ADD COLUMN `rating_style_label` VARCHAR(64);  -- Rating style of a reviewer by average stars: tough critic below 3.2, balanced below 4.1, otherwise generous

-- ------------------------------------------------------------
-- Basketball_men_S  (9 derived columns)
-- ------------------------------------------------------------
USE `Basketball_men_S`;

-- players_teams
ALTER TABLE `players_teams` ADD COLUMN `field_goal_pct` DECIMAL(6,3);  -- Field goal percentage: shots made / shots attempted
ALTER TABLE `players_teams` ADD COLUMN `season_scoring_rank` INT;  -- Scoring rank among all player stints in the same NBA season (DENSE_RAN
ALTER TABLE `players_teams` ADD COLUMN `prev_season_points` DECIMAL(6,1);  -- Points scored in the immediately preceding stint (LAG by year, stint)
ALTER TABLE `players_teams` ADD COLUMN `station_leverage` DECIMAL(12,5);  -- HITS hub score of the player on the player-team graph, minutes-weighted

-- players
ALTER TABLE `players` ADD COLUMN `primary_position_code` CHAR(1);  -- Primary position code: first character of trimmed pos string
ALTER TABLE `players` ADD COLUMN `is_multi_position` TINYINT(1);  -- 1 if player listed under multiple positions (dash in pos code)
ALTER TABLE `players` ADD COLUMN `position_count` TINYINT UNSIGNED;  -- Number of positions listed: dash count + 1
ALTER TABLE `players` ADD COLUMN `height_class` VARCHAR(64);  -- Size class of a player by height in inches: guard-sized below 73, wing-sized below 80, otherwise big-man sized

-- coaches
ALTER TABLE `coaches` ADD COLUMN `coach_season_class` VARCHAR(64);  -- Class of a coaching stint by wins: rebuilding below 25, competitive below 45, otherwise contender

-- ------------------------------------------------------------
-- Financial_ijs_S  (26 derived columns)
-- ------------------------------------------------------------
USE `Financial_ijs_S`;

-- loans
ALTER TABLE `loans` ADD COLUMN `monthly_payment` DECIMAL(10,2);  -- Monthly loan instalment: total amount / duration in months
ALTER TABLE `loans` ADD COLUMN `loan_end_date` DATE;  -- Loan maturity date: start date + duration months
ALTER TABLE `loans` ADD COLUMN `loan_status_label` VARCHAR(50);  -- Loan status decoded from PKDD single-letter code A/B/C/D
ALTER TABLE `loans` ADD COLUMN `account_transaction_count` INT;  -- Transaction count on the linked account: loans -> accounts -> trans
ALTER TABLE `loans` ADD COLUMN `account_owner_birth_year` SMALLINT UNSIGNED;  -- Birth year of the primary account owner: loans -> accounts -> disps(OWNE

-- clients
ALTER TABLE `clients` ADD COLUMN `birth_number_formatted` VARCHAR(10);  -- Czech birth number formatted as YY/MM/DD
ALTER TABLE `clients` ADD COLUMN `birth_year` SMALLINT UNSIGNED;  -- Birth year: 1900 + two-digit prefix of Czech birth number
ALTER TABLE `clients` ADD COLUMN `client_gender` VARCHAR(10);  -- Client gender decoded from Czech birth number month digits (>50 = Fema
ALTER TABLE `clients` ADD COLUMN `birth_month` TINYINT UNSIGNED;  -- Actual birth month: month digits mod 50 (removes female offset)

-- cards
ALTER TABLE `cards` ADD COLUMN `issue_date` DATE;  -- Card issue date: copy of issued
ALTER TABLE `cards` ADD COLUMN `card_holder_district_name` VARCHAR(100);  -- District of the card holder: cards -> disps -> accounts -> districts
ALTER TABLE `cards` ADD COLUMN `card_tier_label` VARCHAR(64);  -- Marketing tier of a payment card decoded from the card type: junior = youth, classic = standard, gold = premium

-- trans
ALTER TABLE `trans` ADD COLUMN `transaction_label` VARCHAR(50);  -- Transaction label: COALESCE trimmed k_symbol, operation, type
ALTER TABLE `trans` ADD COLUMN `days_since_last_transaction` INT;  -- Days since the previous transaction on the same account
ALTER TABLE `trans` ADD COLUMN `days_after_account_opened` INT;  -- Days elapsed between account opening and this transaction
ALTER TABLE `trans` ADD COLUMN `district_crime_per_resident` DECIMAL(10,2);  -- Crimes per 1000 inhabitants in the district of the account
ALTER TABLE `trans` ADD COLUMN `transaction_sequence` BIGINT;  -- Chronological sequence number of this transaction within its account
ALTER TABLE `trans` ADD COLUMN `prev_transaction_amount` DECIMAL(12,2);  -- Amount of the immediately preceding transaction on the same account (L
ALTER TABLE `trans` ADD COLUMN `running_credit_total` DECIMAL(14,2);  -- Running total of credit (PRIJEM) deposits up to this transaction
ALTER TABLE `trans` ADD COLUMN `trans_district_name` VARCHAR(100);  -- District name of the account: trans -> accounts -> districts

-- accounts
ALTER TABLE `accounts` ADD COLUMN `transactions` INT;  -- Number of transactions recorded on this bank account
ALTER TABLE `accounts` ADD COLUMN `total_credited` DECIMAL(14,2);  -- Total amount credited to this account (PRIJEM transactions)
ALTER TABLE `accounts` ADD COLUMN `largest_transaction` DECIMAL(12,2);  -- Largest single transaction amount on this account
ALTER TABLE `accounts` ADD COLUMN `account_vintage_era` VARCHAR(64);  -- Cohort of the account by opening year: founding (up to 1993), growth (1994-1995) or late (1996 and later)

-- orders
ALTER TABLE `orders` ADD COLUMN `destination_mass` DECIMAL(12,5);  -- HITS authority of the destination bank, amount-weighted

-- districts
ALTER TABLE `districts` ADD COLUMN `district_size_class` VARCHAR(64);  -- Size class of a district by inhabitants: small below 85,000, medium below 160,000, large below 480,000, otherwise metropolitan

-- ------------------------------------------------------------
-- Mondial_S  (13 derived columns)
-- ------------------------------------------------------------
USE `Mondial_S`;

-- province
ALTER TABLE `province` ADD COLUMN `pop_density` DECIMAL(10,2);  -- Population density: inhabitants per km^2

-- organization
ALTER TABLE `organization` ADD COLUMN `founding_date` DATE;  -- Organization founding date: copy of Established

-- politics
ALTER TABLE `politics` ADD COLUMN `independence_year` SMALLINT;  -- Independence year extracted from Independence date

-- river
ALTER TABLE `river` ADD COLUMN `outlet_name` VARCHAR(100);  -- River outlet name: COALESCE(Sea, Lake, River)
ALTER TABLE `river` ADD COLUMN `outlet_river_length` DECIMAL(10,2);  -- Length of the river this tributary flows into (via River column)
ALTER TABLE `river` ADD COLUMN `tributary_length_fraction` DECIMAL(6,3);  -- Tributary length as fraction of outlet river length
ALTER TABLE `river` ADD COLUMN `exceeds_outlet_length` TINYINT(1);  -- 1 if this tributary is longer than its outlet river

-- country
ALTER TABLE `country` ADD COLUMN `provinces` INT;  -- Number of provinces belonging to this country
ALTER TABLE `country` ADD COLUMN `standing_weight` DECIMAL(12,5);  -- personalised PageRank, length-weighted transitions, population teleport, dangling redistribution, 15 iterations
ALTER TABLE `country` ADD COLUMN `country_size_class` VARCHAR(64);  -- Size class of a country by area in square kilometres: microstate below 500, small below 60,000, medium below 700,000, otherwise large
ALTER TABLE `country` ADD COLUMN `population_class` VARCHAR(64);  -- Population class of a country: tiny below 900,000, small below 8 million, medium below 60 million, otherwise giant

-- continent
ALTER TABLE `continent` ADD COLUMN `avg_country_pop_density` DECIMAL(10,2);  -- Average population density of countries in this continent weighted by

-- isMember
ALTER TABLE `isMember` ADD COLUMN `affinity_mass` DECIMAL(12,5);  -- HITS hub score of the country over the membership bipartite graph

-- ------------------------------------------------------------
-- stats_S  (25 derived columns)
-- ------------------------------------------------------------
USE `stats_S`;

-- users
ALTER TABLE `users` ADD COLUMN `reputation_log` DECIMAL(8,3);  -- Log10 of user reputation
ALTER TABLE `users` ADD COLUMN `active_days` INT;  -- Days between account creation and last access
ALTER TABLE `users` ADD COLUMN `avg_post_score` DECIMAL(8,2);  -- Average score across all posts authored by this user
ALTER TABLE `users` ADD COLUMN `reputation_class` VARCHAR(64);  -- Reputation class of a user: newcomer below 50, contributor below 800, trusted below 6,000, otherwise expert

-- posts
ALTER TABLE `posts` ADD COLUMN `activity_span_days` INT;  -- Days from post creation to last activity
ALTER TABLE `posts` ADD COLUMN `post_type_label` VARCHAR(20);  -- Post type label decoded from PostTypeId
ALTER TABLE `posts` ADD COLUMN `question_score` INT;  -- Score of the question this answer was posted to (via ParentId)
ALTER TABLE `posts` ADD COLUMN `accepted_answer_score` INT;  -- Score of the accepted answer for this question (via AcceptedAnswerId)
ALTER TABLE `posts` ADD COLUMN `answer_score_delta` INT;  -- Answer score minus the question score it was posted to
ALTER TABLE `posts` ADD COLUMN `is_accepted_answer` TINYINT(1);  -- 1 if this answer is the accepted answer for its question
ALTER TABLE `posts` ADD COLUMN `user_post_rank` INT;  -- Rank of this post within the author's post history by score (RANK)
ALTER TABLE `posts` ADD COLUMN `cumulative_avg_score` DECIMAL(8,2);  -- Running average post score for this author up to and including this po
ALTER TABLE `posts` ADD COLUMN `first_tag` VARCHAR(50);  -- First tag name from Stack Exchange angle-bracket tag string
ALTER TABLE `posts` ADD COLUMN `tag_count` TINYINT UNSIGNED;  -- Number of tags: count of '<' characters in the Tags string
ALTER TABLE `posts` ADD COLUMN `owner_activity_session_number` INT;

-- comments
ALTER TABLE `comments` ADD COLUMN `post_author_tenure_at_post_time` INT;  -- Days the post author had been registered when the post was created
ALTER TABLE `comments` ADD COLUMN `post_author_badge_count` INT;  -- Badge count of the author of the commented post: comments -> posts -> us
ALTER TABLE `comments` ADD COLUMN `conversation_burst` INT;  -- session number of a comment within the user's history, new session after a gap of more than 14 days

-- postLinks
ALTER TABLE `postLinks` ADD COLUMN `pull_coefficient` DECIMAL(12,5);  -- Katz centrality (alpha 0.05, 8 iterations) of the linked post on the post-link graph
ALTER TABLE `postLinks` ADD COLUMN `provenance_mass` DECIMAL(12,5);  -- HITS authority of the linked post, 6 iterations, max-normalised
ALTER TABLE `postLinks` ADD COLUMN `resonance_level` DECIMAL(12,5);  -- clipped diffusion over the row-normalised link graph, damping 0.85, cap 3, 8 iterations

-- badges
ALTER TABLE `badges` ADD COLUMN `merit_stature` DECIMAL(12,5);  -- HITS hub score of the user on the user-badge graph
ALTER TABLE `badges` ADD COLUMN `badge_period` VARCHAR(64);  -- Period in which a badge was earned: early community before 2012, growth years before 2014, otherwise mature community

-- votes
ALTER TABLE `votes` ADD COLUMN `reception_grade` DECIMAL(12,5);  -- HITS authority of the voted post, vote type weights, 5 iterations
ALTER TABLE `votes` ADD COLUMN `attention_flow` DECIMAL(12,5);  -- clipped diffusion over the user-post vote graph (both directions), damping 0.85, cap 3, 6 iterations

-- ------------------------------------------------------------
-- imdb_full_S  (8 derived columns)
-- ------------------------------------------------------------
USE `imdb_full_S`;

-- actors
ALTER TABLE `actors` ADD COLUMN `actor_gender` VARCHAR(10);  -- Actor gender: copy of sex column
ALTER TABLE `actors` ADD COLUMN `actor_last_name` VARCHAR(100);  -- Surname extracted from 'Last, First' formatted name
ALTER TABLE `actors` ADD COLUMN `avg_movie_rating` DECIMAL(4,1);  -- Average IMDB rating across all movies this actor appeared in

-- movies
ALTER TABLE `movies` ADD COLUMN `release_year` SMALLINT UNSIGNED;  -- Release year extracted from parentheses at end of movie title

-- movies2actors
ALTER TABLE `movies2actors` ADD COLUMN `pedigree_mass` DECIMAL(12,5);  -- HITS authority of the movie on the actor-movie graph, leading roles weigh 2
ALTER TABLE `movies2actors` ADD COLUMN `salience_factor` DECIMAL(12,5);  -- HITS hub score of the actor, 5 iterations
ALTER TABLE `movies2actors` ADD COLUMN `billing_label` VARCHAR(64);  -- Billing of an actor in a film from the leading rank: unbilled when 0, top billed up to 3, otherwise supporting cast

-- movies2directors
ALTER TABLE `movies2directors` ADD COLUMN `directing_clout` DECIMAL(12,5);  -- HITS authority of the director on the movie-director graph, max-normalised, 6 iterations

-- ------------------------------------------------------------
-- ErgastF1_S  (32 derived columns)
-- ------------------------------------------------------------
USE `ErgastF1_S`;

-- drivers
ALTER TABLE `drivers` ADD COLUMN `full_name` VARCHAR(100);  -- Driver full name: forename + space + surname
ALTER TABLE `drivers` ADD COLUMN `date_of_birth` DATE;  -- Driver date of birth: copy of dob
ALTER TABLE `drivers` ADD COLUMN `birth_year` SMALLINT;  -- Birth year extracted from dob
ALTER TABLE `drivers` ADD COLUMN `avg_finish_position` DECIMAL(6,2);  -- Average finishing position of this driver across all races
ALTER TABLE `drivers` ADD COLUMN `race_wins` INT;  -- Total F1 races won by this driver (position = 1)
ALTER TABLE `drivers` ADD COLUMN `best_grid_position` INT;  -- Best qualifying grid position ever achieved (min grid > 0)

-- races
ALTER TABLE `races` ADD COLUMN `season_round_label` VARCHAR(50);  -- Race label: year + ' Round ' + round
ALTER TABLE `races` ADD COLUMN `days_since_previous_race` INT;  -- Days between consecutive races in the same season
ALTER TABLE `races` ADD COLUMN `days_to_same_round_last_year` INT;  -- Days between same round number in consecutive seasons
ALTER TABLE `races` ADD COLUMN `next_race_name` VARCHAR(100);  -- Name of the following race in the same season (LEAD by round)
ALTER TABLE `races` ADD COLUMN `season_stage` VARCHAR(64);  -- Stage of the championship by round: opening stretch up to round 5, mid-season up to round 12, otherwise closing stretch

-- pitStops
ALTER TABLE `pitStops` ADD COLUMN `laps_since_last_pitstop` INT;  -- Laps between consecutive pit stops (stop - stop+1)
ALTER TABLE `pitStops` ADD COLUMN `time_since_previous_pitstop` TIME;  -- Clock time elapsed between consecutive pit stops
ALTER TABLE `pitStops` ADD COLUMN `pitstop_constructor_name` VARCHAR(100);  -- Constructor name for this pit stop: pitStops -> results -> constructors

-- driverStandings
ALTER TABLE `driverStandings` ADD COLUMN `points_this_race` FLOAT;  -- Points scored in a single race: current cumulative minus previous

-- constructorStandings
ALTER TABLE `constructorStandings` ADD COLUMN `points_this_race` FLOAT;  -- Constructor points scored in a single race

-- circuits
ALTER TABLE `circuits` ADD COLUMN `races_hosted` INT;  -- Total F1 races held at this circuit across all seasons
ALTER TABLE `circuits` ADD COLUMN `first_race_year` SMALLINT;  -- Earliest year a Formula 1 race was held at this circuit

-- results
ALTER TABLE `results` ADD COLUMN `race_year` SMALLINT;  -- Race year denormalised from races into results
ALTER TABLE `results` ADD COLUMN `race_era` VARCHAR(20);  -- F1 regulatory era of this result classified from race year
ALTER TABLE `results` ADD COLUMN `driver_age_at_race` INT;  -- Driver age in whole years at time of this race result
ALTER TABLE `results` ADD COLUMN `race_constructor_label` VARCHAR(100);  -- Label combining race year and constructor name
ALTER TABLE `results` ADD COLUMN `driver_career_race_number` BIGINT;  -- Sequential career race number for this driver (ROW_NUMBER by raceId)
ALTER TABLE `results` ADD COLUMN `pairwise_clout` DECIMAL(12,4);  -- Keener rating per season (smoothed pairwise shares, skewing function, power iteration, 30 iterations), scaled by driver count
ALTER TABLE `results` ADD COLUMN `momentum_trace` DECIMAL(12,4);  -- irregularly spaced EMA of field-normalised positions gained, finished races only, time half-life
ALTER TABLE `results` ADD COLUMN `tenure_stature` DECIMAL(12,4);  -- Massey rating of the driver per season, place differences capped
ALTER TABLE `results` ADD COLUMN `lineage_grade` DECIMAL(12,4);  -- Colley rating of the driver per season from finishing-order pairs
ALTER TABLE `results` ADD COLUMN `mettle_rating` DECIMAL(12,4);  -- Bradley-Terry strength of the driver per season from finishing-order duels
ALTER TABLE `results` ADD COLUMN `provenance_grade` DECIMAL(12,4);  -- Colley rating of the driver per season from starting-grid pairs
ALTER TABLE `results` ADD COLUMN `points_class` VARCHAR(64);  -- Class of a race result by points: pointless at 0, minor below 3, podium-level below 9, otherwise win-level

-- lapTimes
ALTER TABLE `lapTimes` ADD COLUMN `lap_time_rank` INT;  -- Rank of this driver on a specific lap by lap time (RANK, 1 = fastest)
ALTER TABLE `lapTimes` ADD COLUMN `positions_gained_on_lap` INT;  -- Positions gained or lost on this lap vs previous (LAG(position) - posi

-- ------------------------------------------------------------
-- oulad_S  (15 derived columns)
-- ------------------------------------------------------------
USE `oulad_S`;

-- studentInfo
ALTER TABLE `studentInfo` ADD COLUMN `module_presentation` VARCHAR(20);  -- Course instance: code_module + '-' + code_presentation
ALTER TABLE `studentInfo` ADD COLUMN `pass_flag` TINYINT(1);  -- Pass flag: 1 if Pass or Distinction, 0 otherwise
ALTER TABLE `studentInfo` ADD COLUMN `total_vle_clicks` BIGINT;  -- Total VLE clicks by this student in this module and presentation
ALTER TABLE `studentInfo` ADD COLUMN `final_weighted_score` DECIMAL(8,2);  -- Final weighted assessment score for this student module-presentation
ALTER TABLE `studentInfo` ADD COLUMN `semester_code` CHAR(1);  -- Semester code: last character of code_presentation (J or B)
ALTER TABLE `studentInfo` ADD COLUMN `presentation_year` SMALLINT UNSIGNED;  -- Academic year: first 4 characters of code_presentation cast to UNSIGNE
ALTER TABLE `studentInfo` ADD COLUMN `semester_start_month` VARCHAR(10);  -- Semester start month decoded from presentation code (J=February, B=Oct
ALTER TABLE `studentInfo` ADD COLUMN `course_run_class` VARCHAR(64);  -- Class of the course presentation the student is enrolled in by its length: short below 250 days, standard up to 262, otherwise long
ALTER TABLE `studentInfo` ADD COLUMN `credit_load_label` VARCHAR(64);  -- Study load of the enrolment by studied credits: light below 45, standard below 75, heavy below 130, otherwise overload

-- studentAssessment
ALTER TABLE `studentAssessment` ADD COLUMN `submission_type` VARCHAR(20);  -- Assessment type copied from assessments into studentAssessment
ALTER TABLE `studentAssessment` ADD COLUMN `days_before_due` INT;  -- Days remaining until assessment due date at submission time
ALTER TABLE `studentAssessment` ADD COLUMN `assessment_category` VARCHAR(30);  -- Human-readable category decoded from assessment_type code
ALTER TABLE `studentAssessment` ADD COLUMN `momentum_grade` DECIMAL(12,5);  -- HITS hub score of the student on the student-assessment graph

-- studentVle
ALTER TABLE `studentVle` ADD COLUMN `course_length` INT;  -- Course length (days): studentVle -> vle -> courses

-- assessments
ALTER TABLE `assessments` ADD COLUMN `assessment_stage` VARCHAR(64);  -- Stage of the course in which an assessment falls by its due day: early below 60, mid-course below 150, otherwise late

