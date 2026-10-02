"""Hero meta and top MMR must count ranked games only.

`get_recent_matches_async` feeds both the weekly top-MMR win rate
(`week_games` / `week_wins` in `update_user_mmr`) and the rows saved to
`public_player_matches` that back the hero meta. Before the fix it queried
OpenDota without any mode filter, so Turbo, All Pick and tournaments were
counted as if they were ranked.

OpenDota constants:
  lobby_type 7   = lobby_type_ranked
  game_mode  23  = game_mode_turbo  (matched inside the ranked lobby)
"""

from dota_mmr import (
    RANKED_LOBBY_TYPE,
    TURBO_GAME_MODE,
    is_ranked_match,
)


def test_constants_match_opendota():
    assert RANKED_LOBBY_TYPE == 7
    assert TURBO_GAME_MODE == 23


def test_ranked_all_pick_is_kept():
    assert is_ranked_match({"lobby_type": 7, "game_mode": 22}) is True
    assert is_ranked_match({"lobby_type": 7, "game_mode": 1}) is True


def test_turbo_is_dropped_even_though_it_is_in_the_ranked_lobby():
    assert is_ranked_match({"lobby_type": 7, "game_mode": 23}) is False
    assert is_ranked_match({"game_mode": 23}) is False


def test_non_ranked_lobbies_are_dropped():
    assert is_ranked_match({"lobby_type": 1, "game_mode": 1}) is False
    assert is_ranked_match({"lobby_type": 2, "game_mode": 22}) is False


def test_missing_lobby_type_is_treated_as_ranked():
    # The OpenDota query already asks for lobby_type=7, so a row without the
    # field still came back from the ranked pool and must not be discarded.
    assert is_ranked_match({"lobby_type": 7}) is True
    assert is_ranked_match({}) is True
