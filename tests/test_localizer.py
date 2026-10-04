"""localizer: プリセットの合成、修正リストの検証・適用・描画、戻す操作（LLM はフェイク）"""

import json
from types import SimpleNamespace

import pytest

from divergence_z.localizer import (build_policy, list_presets, load_ledger, localize_chapter,
                                    set_edit_status, validate_edits)

SEGMENTS = [
    {"id": "P001", "source": "탕고도오랑 냄새가 난다.", "target": "タンゴドーラン（整髪料）の匂いがする。"},
    {"id": "P002", "source": "젠장, 신이시여.", "target": "くそ、神よ。神よ、なぜだ。"},
    {"id": "P003", "source": "돼지고기를 먹었다.", "target": "豚肉を食べた。"},
]


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, user, **kw):
        return SimpleNamespace(text="```json\n" + json.dumps(self.payload, ensure_ascii=False) + "\n```")


@pytest.fixture
def l0(tmp_path):
    d = tmp_path / "translations" / "ja"
    d.mkdir(parents=True)
    (d / "ch01.ja.segments.json").write_text(json.dumps(SEGMENTS, ensure_ascii=False), encoding="utf-8")
    (d / "ch01.ja.md").write_text("x", encoding="utf-8")
    return d


def test_builtin_presets_load():
    ids = {p["id"] for p in list_presets()}
    assert {"pg15", "halal", "market_adapt", "diagnose_only"} <= ids


def test_policy_merge_and_override():
    p = build_policy(["market_adapt", "pg15"], {"violence": {"action": "keep"}})
    assert p.name == "market_adapt+pg15"
    assert p.domains["commodity"].action == "substitute"
    assert p.domains["sexual"].action == "soften"
    assert "violence" not in p.active()


def test_validation_rules():
    p = build_policy(["market_adapt"])
    raw = [
        {"seg": "P001", "domain": "commodity", "action": "substitute", "before": "タンゴドーラン（整髪料）", "after": "ポマード"},
        {"seg": "P002", "domain": "religion", "action": "soften", "before": "神よ", "after": "ちくしょう"},   # policy は annotate
        {"seg": "P003", "domain": "food_taboo", "action": "substitute", "before": "豚肉", "after": "鶏肉"},  # 領域が無効
        {"seg": "P001", "domain": "commodity", "action": "substitute", "before": "匂い", "after": "香り"},
        {"seg": "P001", "domain": "commodity", "action": "substitute", "before": "（整髪料）の", "after": "の"},  # 重なり
        {"seg": "P009", "domain": "commodity", "action": "substitute", "before": "a", "after": "b"},
    ]
    out = validate_edits(raw, SEGMENTS, p)
    assert [e["status"] for e in out] == ["applied", "rejected", "rejected", "applied", "rejected", "rejected"]
    assert out[0]["level"] == "L3"


def test_before_must_be_unique():
    p = build_policy(["religious_profanity"])
    out = validate_edits([{"seg": "P002", "domain": "religion", "action": "soften",
                           "before": "神よ", "after": "ちくしょう"}], SEGMENTS, p)
    assert out[0]["status"] == "rejected" and "2 time" in out[0]["reason"]


def test_annotate_keeps_original():
    p = build_policy(["reader_notes"])
    out = validate_edits([{"seg": "P003", "domain": "food_taboo", "action": "annotate",
                           "before": "豚肉", "after": "鶏肉"}], SEGMENTS, p)
    assert out[0]["status"] == "rejected"


def test_localize_render_and_revert(l0):
    policy = build_policy(["market_adapt"])
    llm = FakeLLM({"edits": [
        {"seg": "P001", "domain": "commodity", "action": "substitute", "before": "タンゴドーラン（整髪料）",
         "after": "ポマード", "note": "大衆整髪料"},
    ], "diagnoses": [{"seg": "P002", "domain": "religion", "note": "冒涜表現"}]})
    out = l0.parent / "ja@market_adapt"
    r = localize_chapter(l0, "ch01", "ja", policy, llm=llm, out_dir=out)
    assert r.applied == 1
    clean = (out / "ch01.ja.md").read_text(encoding="utf-8")
    annotated = (out / "ch01.ja.annotated.md").read_text(encoding="utf-8")
    assert "ポマードの匂いがする。" in clean and "〔" not in clean
    # 訳文に（）があるので作者の括弧と衝突しない 〔〕 を使う
    assert "ポマード〔L3・商品・生活文化: タンゴドーラン（整髪料）〕の匂い" in annotated
    assert "冒涜表現" in (out / "ch01.ja.diagnosis.md").read_text(encoding="utf-8")
    # L0 は不変
    assert json.loads((l0 / "ch01.ja.segments.json").read_text(encoding="utf-8")) == SEGMENTS

    set_edit_status(out, "ch01", "ja", "E001", "reverted")
    assert "タンゴドーラン（整髪料）の匂い" in (out / "ch01.ja.md").read_text(encoding="utf-8")
    set_edit_status(out, "ch01", "ja", "E001", "applied")
    assert load_ledger(out, "ch01", "ja")["edits"][0]["status"] == "applied"
    assert "ポマード" in (out / "ch01.ja.md").read_text(encoding="utf-8")


def test_marker_switches_when_source_uses_it(l0):
    segs = [{"id": "P001", "source": "〔注〕", "target": "〔注〕タンゴドーラン"}]
    (l0 / "ch01.ja.segments.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
    llm = FakeLLM({"edits": [{"seg": "P001", "domain": "commodity", "action": "substitute",
                              "before": "タンゴドーラン", "after": "ポマード"}], "diagnoses": []})
    out = l0.parent / "ja@x"
    localize_chapter(l0, "ch01", "ja", build_policy(["market_adapt"]), llm=llm, out_dir=out)
    assert "ポマード⟦L3" in (out / "ch01.ja.annotated.md").read_text(encoding="utf-8")


# ep09（날개）で実際に出た緩和を、scope: modifier の検査にかける
EP09 = [
    {"id": "P012", "source": "…", "target": "私はそれを数えもせず、残りの六錠をいっぺんに、がりがりと噛み砕いて食べてしまった。味が滑稽だった。"},
    {"id": "P020", "source": "…", "target": "私の肌へところかまわず噛みついた。痛くて死にそうだ。"},
]


def test_modifier_scope_rejects_predicate_edits_in_japanese():
    p = build_policy(["pg15"])
    raw = [
        {"seg": "P012", "domain": "violence", "action": "soften",
         "before": "がりがりと噛み砕いて食べてしまった", "after": "噛んで服用してしまった"},
        {"seg": "P012", "domain": "violence", "action": "soften",
         "before": "がりがりと噛み砕いて", "after": "噛んで"},
        {"seg": "P020", "domain": "violence", "action": "soften", "before": "ところかまわず", "after": ""},
        {"seg": "P020", "domain": "violence", "action": "soften", "before": "痛くて死にそうだ。", "after": "ひどく痛む。"},
    ]
    out = validate_edits(raw, EP09, p, lang="ja")
    assert [e["status"] for e in out] == ["rejected", "applied", "applied", "rejected"]
    assert "core predicate" in out[0]["reason"]


def test_modifier_check_is_off_for_head_initial_languages():
    p = build_policy(["pg15"])
    segs = [{"id": "P001", "source": "…", "target": "He bit me everywhere."}]
    out = validate_edits([{"seg": "P001", "domain": "violence", "action": "soften",
                           "before": " everywhere", "after": ""}], segs, p, lang="en")
    assert out[0]["status"] == "applied"


def test_scope_override_any():
    p = build_policy(["religious_profanity"])
    segs = [{"id": "P001", "source": "…", "target": "くそ、神め。"}]
    out = validate_edits([{"seg": "P001", "domain": "religion", "action": "soften",
                           "before": "神め。", "after": "ちくしょう。"}], segs, p, lang="ja")
    assert out[0]["status"] == "applied"


def test_predicate_used_as_anchor_is_allowed():
    """述語を目印に含めただけで、述語そのものは変えていない修正は通す（ep04・ep09 の実例）"""
    p = build_policy(["pg15"])
    segs = [
        {"id": "P008", "source": "…", "target": "痒いところを、血が出るまで掻いた。ひりひりする。"},
        {"id": "P009", "source": "…", "target": "それは奥深い快感に相違なかった。"},
        {"id": "P020", "source": "…", "target": "私の肌へところかまわず噛みついた。痛くて死にそうだ。"},
    ]
    raw = [
        {"seg": "P008", "domain": "violence", "action": "soften", "before": "血が出るまで掻いた", "after": "掻いた"},
        {"seg": "P008", "domain": "violence", "action": "soften", "before": "血が出るまで掻いた", "after": "傷になるまで掻いた"},
        {"seg": "P009", "domain": "sexual", "action": "soften", "before": "奥深い快感に相違なかった。", "after": "快感に相違なかった。"},
        {"seg": "P020", "domain": "violence", "action": "soften", "before": "ところかまわず噛みついた", "after": "噛みついた"},
        {"seg": "P020", "domain": "violence", "action": "soften", "before": "痛くて死にそうだ。", "after": "ひどく痛む。"},
    ]
    out = validate_edits(raw, segs, p, lang="ja")
    # 2件目は1件目と重なるので却下（重なり検査）。最後は述語の変更なので却下
    assert [e["status"] for e in out] == ["applied", "rejected", "applied", "applied", "rejected"]
    assert "overlaps" in out[1]["reason"] and "core predicate" in out[4]["reason"]


def test_shared_auxiliary_does_not_hide_a_verb_change():
    p = build_policy(["pg15"])
    out = validate_edits([{"seg": "P012", "domain": "violence", "action": "soften",
                           "before": "がりがりと噛み砕いて食べてしまった", "after": "噛んで服用してしまった"}],
                         EP09, p, lang="ja")
    assert out[0]["status"] == "rejected"


def test_soften_cannot_remove_glossary_term_but_substitute_can():
    from divergence_z.localizer import glossary_terms
    notes = "glossary:\n- source: 센슈얼\n  target: センシュアル\n- source: 탕고도오랑\n  target: タンゴドーラン\n"
    protected = glossary_terms(notes)
    segs = [{"id": "P003", "source": "…", "target": "異国めいたセンシュアルな香り。タンゴドーランの匂い。"}]
    soft = validate_edits([{"seg": "P003", "domain": "sexual", "action": "soften",
                            "before": "異国めいたセンシュアルな香り", "after": "異国めいた香り"}],
                          segs, build_policy(["pg15"]), lang="ja", protected=protected)
    assert soft[0]["status"] == "rejected" and "glossary" in soft[0]["reason"]
    sub = validate_edits([{"seg": "P003", "domain": "commodity", "action": "substitute",
                           "before": "タンゴドーラン", "after": "ポマード"}],
                         segs, build_policy(["market_adapt"]), lang="ja", protected=protected)
    assert sub[0]["status"] == "applied"
