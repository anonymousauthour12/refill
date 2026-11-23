-- prepare_lahman_2014_S.sql
--
-- In the original lahman_2014 two players have the same playerID 'baezda01'
-- (lahmanID 459 and 460). The benchmark copy keeps 459 and has no rows with that
-- playerID in the statistics tables.
--
-- Run this on lahman_2014_S right after copying the database, before alter_tables.sql.
-- It removes 12 rows: one in players, 11 each in batting, pitching, fielding and appearances,
-- and one each in fieldingpost and pitchingpost.

USE `lahman_2014_S`;

DELETE FROM `appearances`  WHERE `playerID` = 'baezda01';
DELETE FROM `batting`      WHERE `playerID` = 'baezda01';
DELETE FROM `fielding`     WHERE `playerID` = 'baezda01';
DELETE FROM `fieldingpost` WHERE `playerID` = 'baezda01';
DELETE FROM `pitching`     WHERE `playerID` = 'baezda01';
DELETE FROM `pitchingpost` WHERE `playerID` = 'baezda01';
DELETE FROM `players`      WHERE `lahmanID` = 460;
