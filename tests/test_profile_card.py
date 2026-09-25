"""Тесты карточки профиля (/profile) — прогресс ЗВАНИЙ (35 звёзд), а не фиссуры.

Проверяем чистые функции прогресса и рендер `generate_profile_card` на всех
краевых случаях: не калиброван, нулевой MMR, Титан, без аватара, без героев,
без наград, кириллица в нике, битый URL аватара.
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dota_mmr  # noqa: E402
from constants import (  # noqa: E402
    PROFILE_CARD_H,
    PROFILE_CARD_LADDER_TOTAL,
    PROFILE_CARD_RANKS_PER_TIER,
    PROFILE_CARD_W,
)
from dota_mmr import (  # noqa: E402
    generate_profile_card,
    rank_mmr_threshold,
    rank_progress,
)


class TestRankProgress:
    """Прогресс званий: звёзды (полоска) + MMR до следующего звания (игла)."""

    def test_legend_iv_progress(self):
        prog = rank_progress(54, 3760)
        assert prog["tier"] == 5
        assert prog["star"] == 4
        assert prog["step"] == 24                      # (5-1)*5 + 4
        assert prog["total"] == PROFILE_CARD_LADDER_TOTAL
        assert prog["left"] == 11
        assert prog["next"] == dota_mmr.rank_to_string(55)
        assert prog["mmr_base"] == 3700
        assert prog["mmr_next"] == 3860
        assert prog["mmr_left"] == 100
        assert prog["mmr_frac"] == pytest.approx(0.375, abs=0.001)
        assert prog["calibrated"] is True
        assert prog["maxed"] is False

    def test_tier_boundary_jumps_to_next_tier(self):
        # Легенда V -> следующее звание уже Властелин I
        prog = rank_progress(55, 3860)
        assert prog["star"] == 5
        assert prog["step"] == 25
        assert prog["next"] == dota_mmr.rank_to_string(61)

    def test_uncalibrated_zero_everything(self):
        prog = rank_progress(0, 0)
        assert prog["calibrated"] is False
        assert prog["maxed"] is False
        assert prog["tier"] == 0
        assert prog["star"] == 0
        assert prog["step"] == 0
        assert prog["frac"] == 0
        assert prog["mmr_frac"] == 0
        assert prog["mmr_next"] == 150                 # Рекрут I
        assert prog["next"] == dota_mmr.rank_to_string(11)

    def test_titan_is_maxed(self):
        prog = rank_progress(85, 5620)
        assert prog["maxed"] is True
        assert prog["tier"] == 8
        assert prog["step"] == PROFILE_CARD_LADDER_TOTAL
        assert prog["left"] == 0
        assert prog["frac"] == 1.0
        assert prog["next"] is None
        assert prog["mmr_next"] is None
        assert prog["mmr_left"] == 0

    def test_zero_star_rank_maps_to_fifth_star(self):
        # В боте возможен rank_tier % 10 == 0 («Легенда 0») — файла медали для него нет
        prog = rank_progress(50, 3700)
        assert prog["star"] == PROFILE_CARD_RANKS_PER_TIER
        assert prog["tier"] == 5
        assert prog["step"] == 25

    def test_rank_tier_derived_from_mmr_when_missing(self):
        prog = rank_progress(0, 3760)
        assert prog["rank_tier"] == dota_mmr.mmr_to_rank_tier(3760)
        assert prog["calibrated"] is True
        assert prog["tier"] == 5

    @pytest.mark.parametrize("bad", [None, "abc", -5, 3.7])
    def test_invalid_inputs_do_not_crash(self, bad):
        prog = rank_progress(bad, bad)
        assert isinstance(prog, dict)
        assert prog["total"] == PROFILE_CARD_LADDER_TOTAL

    def test_never_negative_left(self):
        for rank_tier in (0, 11, 15, 21, 55, 75, 85):
            for mmr in (0, 150, 1000, 3760, 5620, 99999):
                prog = rank_progress(rank_tier, mmr)
                assert prog["left"] >= 0
                assert prog["mmr_left"] >= 0
                assert 0.0 <= prog["frac"] <= 1.0
                assert 0.0 <= prog["mmr_frac"] <= 1.0


class TestRankMmrThreshold:
    """Порог MMR берётся из таблицы mmr_to_rank_tier — round-trip обязателен."""

    def test_round_trip_all_ranks(self):
        for tier in range(1, 9):
            for star in range(1, PROFILE_CARD_RANKS_PER_TIER + 1):
                rank_tier = tier * 10 + star
                threshold = rank_mmr_threshold(rank_tier)
                assert threshold > 0
                # Плато: у Божества V (75) и всех звёзд Титана (81..85) порог 5620,
                # поэтому mmr_to_rank_tier(5620) возвращает 85 — берём совпадение снизу.
                assert dota_mmr.mmr_to_rank_tier(threshold) >= rank_tier
                if rank_tier <= 74:
                    assert dota_mmr.mmr_to_rank_tier(threshold) == rank_tier

    def test_plateau_ranks_all_map_to_titan(self):
        for rank_tier in (75, 81, 82, 83, 84, 85):
            assert rank_mmr_threshold(rank_tier) == 5620
            assert dota_mmr.mmr_to_rank_tier(5620) == 85

    def test_zero_rank_and_invalid(self):
        assert rank_mmr_threshold(0) == 0
        assert rank_mmr_threshold(None) == 0
        assert rank_mmr_threshold("x") == 0

    def test_five_star_threshold_matches_repo_table(self):
        assert rank_mmr_threshold(54) == 3700
        assert rank_mmr_threshold(55) == 3860
        assert rank_mmr_threshold(85) == 5620


class TestProfileAwards:
    """Награды: теги бота + счётчики недели + производные, без дублей."""

    def test_tags_and_counts_are_deduplicated(self):
        awards = dota_mmr._profile_awards(
            ["weekly_mvp", "weekly_top2"], {"weekly_mvp": 3, "weekly_top2": 2}
        )
        keys = [a["key"] for a in awards]
        assert keys.count("weekly_mvp") == 1
        assert keys.count("weekly_top2") == 1
        assert len(keys) == len(set(keys))

    def test_no_derived_awards_are_invented(self):
        awards = dota_mmr._profile_awards(
            None, None, mmr=6200, total_rolls=350, best_streak=14, message_count=25000
        )
        assert awards == []

    def test_writer_awards_use_persisted_achievements(self):
        awards = dota_mmr._profile_awards(
            achievements={"ah_msg100": 1, "ah_msg1000": 1}
        )
        keys = {a["key"] for a in awards}
        assert keys == {"ah_msg1000"}
        assert "ah_msg500" not in keys
        assert "ah_msg20000" not in keys

    def test_profile_shows_only_highest_writer_award(self):
        awards = dota_mmr._profile_awards(
            achievements={"ah_msg100": 1, "ah_msg1000": 1, "ah_msg20000": 1}
        )
        writer_awards = [a for a in awards if a["key"].startswith("ah_msg")]
        assert len(writer_awards) == 1
        assert writer_awards[0]["key"] == "ah_msg20000"
        assert writer_awards[0]["label"] == "ПИСАТЕЛЬ 20000"

    def test_empty_returns_empty_list(self):
        assert dota_mmr._profile_awards(None, None) == []

    def test_garbage_inputs_do_not_crash(self):
        awards = dota_mmr._profile_awards("не-список", {"weekly_mvp": "abc"}, mmr="x")
        assert isinstance(awards, list)

    def test_unknown_tag_ignored(self):
        awards = dota_mmr._profile_awards(["какой-то_тег"], None)
        assert all(a["key"] in {"weekly_mvp", "weekly_top1", "weekly_top2", "weekly_top3",
                                "F1", "F2", "F3", "VIP", "admin_custom"} for a in awards)


def _png_size(data: bytes):
    with Image.open(io.BytesIO(data)) as img:
        return img.size, img.format


class TestGenerateProfileCard:
    """Рендер карточки: всегда PNG нужного размера, без исключений."""

    FULL_KWARGS = dict(
        username="seredin",
        steam_nickname="Seredin999",
        steam_id=123456789,
        mmr=3760,
        rank_tier=54,
        fissure=1234.5,
        total_rolls=421,
        weekly_rolls=17,
        current_streak=4,
        best_streak=12,
        message_count=34567,
        week_games=22,
        week_wins=13,
        dota_total_games=1500,
        dota_wins=780,
        top_heroes=[
            {"short_name": "axe", "picks": 9},
            {"short_name": "pudge", "picks": 7},
            {"short_name": "invoker", "picks": 5},
        ],
        tags=["weekly_mvp", "fissure_master"],
        award_counts={"weekly_mvp": 3, "weekly_top2": 2, "weekly_top3": 1},
        position=7,
    )

    def test_full_card_is_png_with_expected_size(self):
        data = generate_profile_card(**self.FULL_KWARGS)
        assert isinstance(data, bytes) and len(data) > 5000
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        size, fmt = _png_size(data)
        assert size == (PROFILE_CARD_W, PROFILE_CARD_H)
        assert fmt == "PNG"

    def test_minimal_card_without_any_data(self):
        data = generate_profile_card()
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_uncalibrated_card(self):
        data = generate_profile_card(username="newbie", mmr=0, rank_tier=0)
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_titan_card(self):
        data = generate_profile_card(username="titan", mmr=7000, rank_tier=85)
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_rank_zero_star_card(self):
        data = generate_profile_card(username="edge", mmr=3700, rank_tier=50)
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_broken_avatar_url_falls_back_to_placeholder(self):
        data = generate_profile_card(
            avatar_url="not-a-valid-url", username="broken", rank_tier=33, mmr=2000
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_garbage_avatar_bytes_falls_back(self):
        data = generate_profile_card(
            avatar_url=b"definitely not an image", username="garbage", rank_tier=33
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_local_avatar_file_is_used(self, tmp_path):
        avatar_path = tmp_path / "avatar.png"
        Image.new("RGBA", (96, 64), (200, 40, 40, 255)).save(avatar_path)
        data = generate_profile_card(
            avatar_url=str(avatar_path), username="local", rank_tier=45, mmr=3090
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_cyrillic_text_renders(self):
        data = generate_profile_card(
            username="Середин",
            steam_nickname="Властелин Фиссур",
            mmr=4300,
            rank_tier=63,
            tags=["fissure_master"],
            top_heroes=[{"short_name": "не_герой", "picks": 3}],
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_missing_hero_assets_do_not_break_card(self):
        data = generate_profile_card(
            username="noheroes",
            top_heroes=[{"short_name": "zzz_nonexistent", "picks": 2}, {}, None],
            rank_tier=25,
            mmr=1570,
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_no_awards_and_no_steam_show_placeholders(self):
        data = generate_profile_card(username="solo", message_count=5)
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    def test_extremely_long_values_are_truncated_not_crashing(self):
        data = generate_profile_card(
            username="x" * 300,
            steam_nickname="nickname " * 40,
            mmr=999999,
            rank_tier=85,
            message_count=999999999,
            total_rolls=999999,
            best_streak=999,
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"

    @pytest.mark.parametrize("rank_tier", [0, 11, 15, 25, 35, 45, 55, 65, 75, 85, 50])
    def test_every_tier_renders(self, rank_tier, tmp_path):
        data = generate_profile_card(
            username=f"tier{rank_tier}",
            rank_tier=rank_tier,
            mmr=rank_mmr_threshold(rank_tier),
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"
        out = tmp_path / f"card_{rank_tier}.png"
        out.write_bytes(data)
        assert out.stat().st_size > 3000

    def test_background_is_cached_between_renders(self):
        first = dota_mmr._profile_background()
        second = dota_mmr._profile_background()
        assert first is second
        assert first.size == (PROFILE_CARD_W, PROFILE_CARD_H)

    def test_rank_medal_matches_repo_assets(self):
        # Титан: только 5-я звезда (rank_8_5.webp), rank_8_1..8_4 в репозитории нет
        assert dota_mmr._profile_rank_medal(85, 64) is not None
        assert dota_mmr._profile_rank_medal(54, 64) is not None
        assert dota_mmr._profile_rank_medal(0, 64) is None


class TestProfileCardRegressions:
    """Регрессии, найденные на превью: «тофу»-глифы, обрезка наград, «лучший 0»."""

    def test_star_glyph_is_absent_in_repo_font(self):
        # Причина фикса: в NotoSans нет «★» и Pillow рисовал .notdef-квадрат
        font = dota_mmr._profile_font("bold", 17)
        assert dota_mmr._profile_supports_glyph(font, "★") is False

    def test_clean_text_drops_unsupported_glyphs(self):
        font = dota_mmr._profile_font("regular", 12)
        cleaned = dota_mmr._profile_clean_text("осталось 11 ★ · 100 MMR", font)
        assert "★" not in cleaned
        assert "осталось 11" in cleaned and "100 MMR" in cleaned
        assert dota_mmr._profile_clean_text("🔥Середин", font) == "Середин"
        assert dota_mmr._profile_clean_text(None, font) == ""
        assert dota_mmr._profile_clean_text("Середин 123", font) == "Середин 123"

    def test_card_strings_survive_cleaning(self):
        font = dota_mmr._profile_font("bold", 17)
        for text in ("ДО ЛЕГЕНДА 5", "МАКСИМАЛЬНОЕ ЗВАНИЕ", "ОТКАЛИБРУЙТЕСЬ", "24 / 35",
                     "выше уже некуда — Титан покорён"):
            assert dota_mmr._profile_clean_text(text, font) == text

    def test_rank_only_design_no_mmr_no_progress(self):
        # Новый дизайн: MMR-числа и «прогресс звания» убраны — на карточке только ранг
        import inspect

        src = inspect.getsource(dota_mmr.generate_profile_card)
        for banned in ("MMR\"", "ПРОГРЕСС ЗВАНИЯ", "ПРОГРЕСС ДО СЛЕДУЮЩЕГО ЗВАНИЯ",
                       "звёзд звания", "_profile_bottom_captions"):
            assert banned not in src, banned
        # Геометрия утверждённого макета 1024x500: без Steam вместо героев —
        # текст из стартовой карточки (длина фиссуры + всего сообщений)
        assert "Всего сообщений" in src
        assert "Герои недели".lower() in src.lower() or "герои" in src.lower()

    def test_awards_capped_to_five_with_counter(self):
        assert dota_mmr._profile_awards_cap(5) == (5, "5 шт.")
        assert dota_mmr._profile_awards_cap(8) == (5, "5 из 8")
        assert dota_mmr._profile_awards_cap(6) == (5, "5 из 6")
        layout = dota_mmr._profile_awards_layout(5)
        assert layout["rows"] == 1 and layout["tile"] == 120.0
        assert layout["top"] == 245.0
        assert layout["bottom"] <= PROFILE_CARD_H - 4

    @pytest.mark.parametrize("current,best,expected", [
        (0, 0, None),
        (1, 0, "лучший 1"),
        (3, 11, "лучший 11"),
        (0, 27, "лучший 27"),
        (12, 4, "лучший 12"),
        (None, None, None),
        ("x", 5, "лучший 5"),
    ])
    def test_streak_sub_never_shows_zero_record(self, current, best, expected):
        assert dota_mmr._profile_streak_sub(current, best) == expected

    def test_nine_awards_and_emoji_nickname_render(self):
        data = generate_profile_card(
            username="🛡️legenda",
            steam_nickname="Legend 🔥",
            mmr=6200,
            rank_tier=85,
            total_rolls=350,
            best_streak=15,
            message_count=25000,
            tags=["weekly_mvp", "weekly_top2", "weekly_top3",
                  "fissure_master", "admin_custom"],
            award_counts={"weekly_mvp": 9, "weekly_top2": 4, "weekly_top3": 2},
        )
        assert isinstance(data, bytes) and data[:4] == b"\x89PNG"
        size, _ = _png_size(data)
        assert size == (PROFILE_CARD_W, PROFILE_CARD_H)


