"""Accuracy tests for visual-selection anchoring.

The agent never sees the page. Everything it knows about a selection comes from
this layer, so these tests are organised around the ways an anchor can silently
point at the WRONG element — duplicate ids, repeated card markup, inline
scripts shifting sibling indices, subtrees rewritten between selection and use.
A wrong anchor is worse than a rejected one: it makes the agent confidently
edit the wrong lines. Every ambiguous case below must raise, not guess.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "service" / "server" / "workbench.py"
SPEC = importlib.util.spec_from_file_location("workbench_context", MODULE_PATH)
workbench = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = workbench
SPEC.loader.exec_module(workbench)


def tree(source):
    return workbench.parse_document_tree(source)


def resolve(source, descriptor):
    parser, body = tree(source)
    return parser, body, workbench.resolve_anchor(parser, body, descriptor)


def describe(source, descriptor):
    parser, body, node = resolve(source, descriptor)
    return workbench.describe_anchor(parser, body, node)


def page(body_html, head_extra="", body_extra=""):
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"{head_extra}</head>\n<body>\n{body_html}\n{body_extra}</body>\n</html>\n"
    )


# Repeated, near-identical markup is the single most dangerous shape: three
# cards whose only difference is their text. Selectors alone cannot separate
# them, so the structural path has to carry the weight.
CARDS = page(
    """<main>
  <section class="pricing">
    <article class="card"><h3>Starter</h3><button class="buy">购买</button></article>
    <article class="card"><h3>Pro</h3><button class="buy">购买</button></article>
    <article class="card"><h3>Team</h3><button class="buy">购买</button></article>
  </section>
</main>"""
)


class PathResolutionTests(unittest.TestCase):
    def test_distinguishes_identical_siblings_by_path(self):
        for index, expected in enumerate(["Starter", "Pro", "Team"]):
            node = resolve(CARDS, {"tag": "article", "path": [0, 0, index]})[2]
            self.assertEqual(workbench.node_text(CARDS, node), f"{expected} 购买")

    def test_reaches_nested_leaf_through_repeated_ancestors(self):
        parser, body, node = resolve(CARDS, {"tag": "button", "path": [0, 0, 2, 1]})
        self.assertEqual(node.tag, "button")
        self.assertEqual(workbench.node_path(node, body), [0, 0, 2, 1])
        # The button lives inside the third card, not the first.
        self.assertIn("Team", workbench.node_text(CARDS, node.parent))

    def test_rejects_path_pointing_past_the_end(self):
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(CARDS, {"tag": "article", "path": [0, 0, 9]})
        self.assertEqual(caught.exception.code, "ANCHOR_NOT_FOUND")

    def test_rejects_tag_mismatch_when_tree_shifted(self):
        # The path still resolves, but to a different kind of element: the user
        # picked a button and the file now has a heading there.
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(CARDS, {"tag": "button", "path": [0, 0, 0, 0]})
        self.assertEqual(caught.exception.code, "ANCHOR_NOT_FOUND")

    def test_round_trips_every_element_in_the_document(self):
        # Whatever path the describer emits must resolve back to the same node.
        parser, body = tree(CARDS)
        for node in parser.nodes:
            if not node.is_inside(body):
                continue
            path = workbench.node_path(node, body)
            self.assertIsNotNone(path, node.tag)
            self.assertIs(workbench.node_at_path(body, path), node)


class InlineScriptIndexTests(unittest.TestCase):
    """Body scripts are stripped before GrapesJS sees the document.

    If the server counted them as children, every sibling index after an inline
    script would be off by one and the selection would land on its neighbour.
    """

    SOURCE = page(
        """<main>
  <h1>标题</h1>
  <script>window.a = 1</script>
  <p class="lead">说明文字</p>
  <button id="cta">开始</button>
</main>"""
    )

    def test_script_does_not_consume_a_sibling_index(self):
        node = resolve(self.SOURCE, {"tag": "p", "path": [0, 1]})[2]
        self.assertEqual(workbench.node_text(self.SOURCE, node), "说明文字")

    def test_element_after_script_keeps_stable_index(self):
        node = resolve(self.SOURCE, {"tag": "button", "path": [0, 2]})[2]
        self.assertEqual(node.attrs.get("id"), "cta")

    def test_structural_children_excludes_scripts(self):
        parser, body = tree(self.SOURCE)
        main = workbench.node_at_path(body, [0])
        self.assertEqual([child.tag for child in workbench.structural_children(main)], ["h1", "p", "button"])


class IdentityResolutionTests(unittest.TestCase):
    SOURCE = page(
        """<main>
  <h1 id="title">标题</h1>
  <div data-wb-id="hero-copy"><p>正文</p></div>
  <button data-mode="edit">编辑</button>
</main>"""
    )

    def test_resolves_each_supported_identity_attribute(self):
        cases = [
            ({"name": "id", "value": "title"}, "h1"),
            ({"name": "data-wb-id", "value": "hero-copy"}, "div"),
            ({"name": "data-mode", "value": "edit"}, "button"),
        ]
        for identity, tag in cases:
            node = resolve(self.SOURCE, {"tag": tag, "identity": identity})[2]
            self.assertEqual(node.tag, tag)

    def test_identity_wins_over_a_stale_path(self):
        # The agent reordered the page after the user selected; the identity is
        # still correct and must take priority over the now-wrong path.
        node = resolve(self.SOURCE, {"tag": "h1", "identity": {"name": "id", "value": "title"}, "path": [0, 2]})[2]
        self.assertEqual(node.attrs["id"], "title")

    def test_missing_identity_falls_back_to_path(self):
        node = resolve(self.SOURCE, {"tag": "button", "identity": {"name": "id", "value": "gone"}, "path": [0, 2]})[2]
        self.assertEqual(node.attrs.get("data-mode"), "edit")

    # GrapesJS mints ids like `id="iftsf"` for its own style rules, and an earlier
    # bug let them reach the source file. Such an id names nothing a human would
    # recognise, so when an element carries both, the label must come from the
    # `data-wb-id` we minted deliberately.
    def test_our_own_identity_is_preferred_over_a_page_id(self):
        source = page('<main><section data-wb-id="pricing-pro" id="iftsf" class="card">专业版</section></main>')
        parser, body, node = resolve(source, {"tag": "section", "path": [0, 0]})
        self.assertEqual(workbench.identity_of(node), {"name": "data-wb-id", "value": "pricing-pro"})
        self.assertEqual(workbench.selector_of(node), '[data-wb-id="pricing-pro"]')

    def test_a_page_id_is_still_used_when_it_is_the_only_identity(self):
        source = page('<main><section id="cta">立即购买</section></main>')
        parser, body, node = resolve(source, {"tag": "section", "path": [0, 0]})
        self.assertEqual(workbench.selector_of(node), "#cta")

    def test_both_identities_remain_resolvable_anchors(self):
        # Preferring one for the LABEL must not make the other unusable, or a
        # descriptor captured before a reorder would stop resolving.
        source = page('<main><section data-wb-id="pricing-pro" id="iftsf">专业版</section></main>')
        for identity in ({"name": "data-wb-id", "value": "pricing-pro"}, {"name": "id", "value": "iftsf"}):
            node = resolve(source, {"tag": "section", "identity": identity})[2]
            self.assertEqual(node.attrs["data-wb-id"], "pricing-pro")

    def test_rejects_unknown_element_without_path(self):
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(self.SOURCE, {"tag": "h1", "identity": {"name": "id", "value": "missing"}})
        self.assertEqual(caught.exception.code, "ANCHOR_NOT_FOUND")


class AmbiguityTests(unittest.TestCase):
    DUPLICATE = page(
        """<main>
  <section><span id="dup">第一处</span></section>
  <section><span id="dup">第二处</span></section>
</main>"""
    )

    def test_duplicate_identity_without_path_is_refused(self):
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(self.DUPLICATE, {"tag": "span", "identity": {"name": "id", "value": "dup"}})
        self.assertEqual(caught.exception.code, "ANCHOR_AMBIGUOUS")
        self.assertEqual(caught.exception.status, 409)

    def test_duplicate_identity_is_disambiguated_by_path(self):
        node = resolve(self.DUPLICATE, {
            "tag": "span",
            "identity": {"name": "id", "value": "dup"},
            "path": [0, 1, 0],
        })[2]
        self.assertEqual(workbench.node_text(self.DUPLICATE, node), "第二处")

    def test_duplicate_identity_with_unrelated_path_stays_refused(self):
        # The path does not land on either duplicate, so nothing narrows it.
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(self.DUPLICATE, {
                "tag": "span",
                "identity": {"name": "id", "value": "dup"},
                "path": [0, 0],
            })
        self.assertEqual(caught.exception.code, "ANCHOR_AMBIGUOUS")


class TextHintTests(unittest.TestCase):
    """A path is only as good as the tree it was computed against."""

    SOURCE = page(
        """<ul>
  <li>第一项内容</li>
  <li>第二项内容</li>
</ul>"""
    )

    def test_hint_matching_content_is_accepted(self):
        node = resolve(self.SOURCE, {"tag": "li", "path": [0, 1], "textHint": "第二项内容"})[2]
        self.assertEqual(workbench.node_text(self.SOURCE, node), "第二项内容")

    def test_hint_contradicting_content_is_refused(self):
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(self.SOURCE, {"tag": "li", "path": [0, 1], "textHint": "完全不同的一段文字"})
        self.assertEqual(caught.exception.code, "ANCHOR_NOT_FOUND")

    def test_hint_is_not_enforced_when_identity_matched(self):
        # Identity is the stronger signal; text drifts as the agent rewrites copy.
        source = page('<main><h1 id="t">新文案</h1></main>')
        node = resolve(source, {"tag": "h1", "identity": {"name": "id", "value": "t"}, "textHint": "旧文案"})[2]
        self.assertEqual(node.attrs["id"], "t")

    # `node_text` puts a space where each tag was, but the browser's `textContent`
    # concatenates with nothing between. Comparing those literally rejected every
    # correct anchor in tightly-written HTML, so the check ignores whitespace.
    def test_hint_matches_across_tag_boundary_whitespace(self):
        source = page('<main><section class="card"><h3>专业版</h3><p>￥99</p><button>选择</button></section></main>')
        # What the browser reports: no spaces, because the markup supplied none.
        node = resolve(source, {"tag": "section", "path": [0, 0], "textHint": "专业版￥99选择"})[2]
        self.assertEqual(node.attrs.get("class"), "card")

    def test_hint_matches_when_source_wraps_across_lines(self):
        source = page("""<main>
  <section class="card">
    <h3>专业版</h3>
    <p>￥99</p>
  </section>
</main>""")
        node = resolve(source, {"tag": "section", "path": [0, 0], "textHint": "专业版￥99"})[2]
        self.assertEqual(node.attrs.get("class"), "card")

    def test_whitespace_insensitivity_does_not_accept_different_content(self):
        # The relaxation must not become "anything matches".
        source = page('<main><section class="card"><h3>专业版</h3></section></main>')
        with self.assertRaises(workbench.WorkbenchError) as caught:
            resolve(source, {"tag": "section", "path": [0, 0], "textHint": "旗舰版￥299"})
        self.assertEqual(caught.exception.code, "ANCHOR_NOT_FOUND")


class SnippetFidelityTests(unittest.TestCase):
    """The snippet is the agent's `old_string`; it must be byte-exact."""

    def test_snippet_is_a_literal_substring_of_the_source(self):
        item = describe(CARDS, {"tag": "article", "path": [0, 0, 1]})
        self.assertFalse(item["snippetTruncated"])
        self.assertIn(item["snippet"], CARDS)
        self.assertEqual(CARDS[item["startOffset"]:item["endOffset"]], item["snippet"])

    def test_snippet_covers_the_whole_element_including_close_tag(self):
        item = describe(CARDS, {"tag": "article", "path": [0, 0, 0]})
        self.assertTrue(item["snippet"].startswith('<article class="card">'))
        self.assertTrue(item["snippet"].endswith("</article>"))
        self.assertIn("Starter", item["snippet"])

    def test_void_element_snippet_stops_at_the_start_tag(self):
        source = page('<main><img src="a.png" alt="图"><p>后续</p></main>')
        item = describe(source, {"tag": "img", "path": [0, 0]})
        self.assertEqual(item["snippet"], '<img src="a.png" alt="图">')
        self.assertNotIn("后续", item["snippet"])

    def test_oversized_element_is_truncated_but_marked(self):
        source = page("<main><section>" + "<p>很长的一段内容</p>" * 400 + "</section></main>")
        item = describe(source, {"tag": "section", "path": [0, 0]})
        self.assertTrue(item["snippetTruncated"])
        self.assertIn("省略", item["snippet"])
        self.assertLess(len(item["snippet"]), 2200)


class LineNumberTests(unittest.TestCase):
    def test_line_range_matches_the_real_file_lines(self):
        source = page("<main>\n  <h1>标题</h1>\n  <p>说明</p>\n</main>")
        lines = source.splitlines()
        item = describe(source, {"tag": "p", "path": [0, 1]})
        self.assertEqual(item["lineStart"], item["lineEnd"])
        self.assertIn("<p>说明</p>", lines[item["lineStart"] - 1])

    def test_multi_line_element_reports_a_spanning_range(self):
        item = describe(CARDS, {"tag": "section", "path": [0, 0]})
        self.assertLess(item["lineStart"], item["lineEnd"])
        self.assertIn("<section", CARDS.splitlines()[item["lineStart"] - 1])
        self.assertIn("</section>", CARDS.splitlines()[item["lineEnd"] - 1])

    def test_first_body_element_is_not_reported_as_line_one(self):
        item = describe(CARDS, {"tag": "main", "path": [0]})
        self.assertGreater(item["lineStart"], 1)


class DescriptionTests(unittest.TestCase):
    SOURCE = page(
        """<main>
  <section class="hero">
    <h1 class="hero-title" data-wb-id="hero-title">让页面进入可编辑状态</h1>
    <button class="btn primary" data-action="open-dialog" data-target="signup">开始使用</button>
  </section>
</main>"""
    )

    def test_reports_selector_identity_and_ancestry(self):
        item = describe(self.SOURCE, {"tag": "h1", "identity": {"name": "data-wb-id", "value": "hero-title"}})
        self.assertEqual(item["selector"], '[data-wb-id="hero-title"]')
        self.assertEqual(item["identity"], {"name": "data-wb-id", "value": "hero-title"})
        self.assertEqual(item["ancestors"], ["main", "section.hero"])
        self.assertEqual(item["text"], "让页面进入可编辑状态")

    def test_reports_behaviour_attributes_for_interactive_elements(self):
        item = describe(self.SOURCE, {"tag": "button", "path": [0, 0, 1]})
        self.assertEqual(item["behavior"], {"data-action": "open-dialog", "data-target": "signup"})
        self.assertEqual(item["selector"], "button.btn.primary")

    def test_anchorless_element_is_reported_as_such(self):
        item = describe(page("<main><p>纯文本</p></main>"), {"tag": "p", "path": [0, 0]})
        self.assertIsNone(item["identity"])

    def test_text_extraction_ignores_nested_script_content(self):
        source = page("<main><div>可见文字<script>var secret = 1</script></div></main>")
        item = describe(source, {"tag": "div", "path": [0, 0]})
        self.assertEqual(item["text"], "可见文字")
        self.assertNotIn("secret", item["text"])


class RelatedCssTests(unittest.TestCase):
    SOURCE = page(
        '<main><section class="hero"><h1 class="hero-title" id="title">标题</h1></section><p class="note">注</p></main>',
        head_extra="""<style>
.hero-title { font-size: 64px; color: #111; }
.note { color: gray; }
#title { letter-spacing: -0.04em; }
@media (max-width: 600px) { .hero-title { font-size: 32px; } }
</style>
""",
    )

    def selection_css(self, descriptor):
        parser, body, node = resolve(self.SOURCE, descriptor)
        rules = workbench.document_css_rules(self.SOURCE)
        return workbench.related_css(parser, self.SOURCE, [node], rules)

    def test_collects_class_and_id_rules_for_the_selection(self):
        selectors = [rule["selector"] for rule in self.selection_css({"tag": "h1", "path": [0, 0, 0]})]
        self.assertIn(".hero-title", selectors)
        self.assertIn("#title", selectors)

    def test_excludes_rules_belonging_to_other_elements(self):
        selectors = [rule["selector"] for rule in self.selection_css({"tag": "h1", "path": [0, 0, 0]})]
        self.assertNotIn(".note", selectors)

    def test_keeps_media_queries_that_override_the_selection(self):
        selectors = [rule["selector"] for rule in self.selection_css({"tag": "h1", "path": [0, 0, 0]})]
        self.assertTrue(any(item.startswith("@media") for item in selectors))

    def test_ignores_the_grapesjs_override_block(self):
        source = page("<main><p class=\"x\">文</p></main>", head_extra="<style data-grapesjs-overrides>.x{color:red}</style>\n")
        self.assertEqual(workbench.document_css_rules(source), [])

    def test_splits_nested_at_rules_without_cutting_them(self):
        css = "@media (min-width: 700px) { .a { color: red; } .b { color: blue; } }\n.c { color: green; }"
        rules = workbench.split_css_rules(css, 0)
        self.assertEqual([rule["selector"] for rule in rules], ["@media (min-width: 700px)", ".c"])
        self.assertIn(".b { color: blue; }", rules[0]["text"])

    def test_brace_inside_string_does_not_split_a_rule(self):
        rules = workbench.split_css_rules('.a::after { content: "}"; color: red; }', 0)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["selector"], ".a::after")

    def test_comment_containing_brace_is_skipped(self):
        rules = workbench.split_css_rules("/* { unbalanced */ .a { color: red; }", 0)
        self.assertEqual([rule["selector"] for rule in rules], [".a"])


class RelatedScriptTests(unittest.TestCase):
    SOURCE = page(
        """<main>
  <button data-action="toggle" data-target="faq-1">展开</button>
  <div data-wb-id="faq-1" hidden>答案</div>
  <p class="unrelated">无关段落</p>
</main>""",
        body_extra="""<script>
document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-action="toggle"]')
  if (!trigger) return
  const target = document.querySelector(`[data-wb-id="${trigger.dataset.target}"]`)
  if (target) target.hidden = !target.hidden
})
</script>
""",
    )

    def scripts_for(self, descriptor):
        parser, body, node = resolve(self.SOURCE, descriptor)
        return workbench.related_scripts(parser, self.SOURCE, [node])

    def test_finds_the_handler_driving_the_selected_control(self):
        blocks = self.scripts_for({"tag": "button", "path": [0, 0]})
        self.assertEqual(len(blocks), 1)
        self.assertIn("addEventListener", blocks[0]["text"])
        self.assertIn("toggle", blocks[0]["matches"])

    def test_reports_the_script_line_range(self):
        block = self.scripts_for({"tag": "button", "path": [0, 0]})[0]
        lines = self.SOURCE.splitlines()
        self.assertIn("<script>", lines[block["lineStart"] - 1])
        self.assertIn("</script>", lines[block["lineEnd"] - 1])

    def test_element_with_no_behavioural_link_pulls_no_script(self):
        self.assertEqual(self.scripts_for({"tag": "p", "path": [0, 2]}), [])


class ContextPacketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "page.html"

    def write(self, source):
        self.file.write_text(source, encoding="utf-8")
        return self.file

    def test_packet_carries_file_revision_and_selections(self):
        self.write(CARDS)
        packet = workbench.build_selection_context(self.file, [
            {"tag": "article", "path": [0, 0, 0]},
            {"tag": "article", "path": [0, 0, 2]},
        ])
        self.assertEqual(packet["filePath"], str(self.file))
        self.assertEqual(len(packet["revision"]), 64)
        self.assertEqual(len(packet["selections"]), 2)

    def test_child_selection_is_collapsed_into_its_selected_ancestor(self):
        # Selecting a card and then its button must not send the same source
        # twice, or the instruction becomes ambiguous.
        self.write(CARDS)
        packet = workbench.build_selection_context(self.file, [
            {"tag": "article", "path": [0, 0, 1]},
            {"tag": "button", "path": [0, 0, 1, 1]},
        ])
        self.assertEqual(len(packet["selections"]), 1)
        self.assertEqual(packet["selections"][0]["tag"], "article")
        self.assertEqual(packet["collapsed"], 1)

    def test_sibling_selections_are_both_kept(self):
        self.write(CARDS)
        packet = workbench.build_selection_context(self.file, [
            {"tag": "h3", "path": [0, 0, 0, 0]},
            {"tag": "button", "path": [0, 0, 0, 1]},
        ])
        self.assertEqual(len(packet["selections"]), 2)
        self.assertEqual(packet["collapsed"], 0)

    def test_empty_selection_is_refused(self):
        self.write(CARDS)
        with self.assertRaises(workbench.WorkbenchError) as caught:
            workbench.build_selection_context(self.file, [])
        self.assertEqual(caught.exception.code, "INVALID_ANCHOR")

    def test_selection_count_is_capped(self):
        self.write(CARDS)
        descriptors = [{"tag": "article", "path": [0, 0, 0]}] * (workbench.MAX_CONTEXT_SELECTIONS + 1)
        with self.assertRaises(workbench.WorkbenchError):
            workbench.build_selection_context(self.file, descriptors)


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "page.html"

    def packet(self, source, descriptors):
        self.file.write_text(source, encoding="utf-8")
        return workbench.build_selection_context(self.file, descriptors)

    def test_markdown_states_the_file_and_anchor(self):
        markdown = self.packet(
            page('<main><h1 data-wb-id="hero-title">标题</h1></main>'),
            [{"tag": "h1", "identity": {"name": "data-wb-id", "value": "hero-title"}}],
        )["markdown"]
        self.assertIn(str(self.file), markdown)
        self.assertIn('[data-wb-id="hero-title"]', markdown)
        self.assertIn("源码位置：第", markdown)

    def test_markdown_embeds_the_literal_snippet(self):
        markdown = self.packet(CARDS, [{"tag": "article", "path": [0, 0, 1]}])["markdown"]
        self.assertIn("```html", markdown)
        self.assertIn("<h3>Pro</h3>", markdown)

    def test_markdown_explains_the_referent_for_pronoun_instructions(self):
        markdown = self.packet(CARDS, [{"tag": "article", "path": [0, 0, 1]}])["markdown"]
        self.assertIn("这个", markdown)
        self.assertIn("修改约束", markdown)

    def test_markdown_stays_within_the_budget(self):
        source = page("<main>" + "".join(f'<section class="s{i}"><p>内容{i}</p></section>' for i in range(200)) + "</main>")
        descriptors = [{"tag": "section", "path": [0, i]} for i in range(workbench.MAX_CONTEXT_SELECTIONS)]
        markdown = self.packet(source, descriptors)["markdown"]
        self.assertLessEqual(len(markdown.encode("utf-8")), workbench.MAX_CONTEXT_BYTES + 64)


class IdentityPromotionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "page.html"

    def write(self, source):
        self.file.write_text(source, encoding="utf-8")
        return workbench.read_document(self.file)["revision"]

    def test_assigns_a_readable_id_to_an_anchorless_element(self):
        revision = self.write(page('<main><h1 class="hero-title">标题</h1></main>'))
        result = workbench.promote_identities(self.file, [{"tag": "h1", "path": [0, 0]}], revision)
        self.assertTrue(result["changed"])
        self.assertEqual(result["assigned"][0]["identity"]["name"], "data-wb-id")
        self.assertEqual(result["assigned"][0]["identity"]["value"], "hero-title")
        self.assertIn('data-wb-id="hero-title"', self.file.read_text(encoding="utf-8"))

    def test_leaves_existing_identity_untouched(self):
        source = page('<main><h1 id="title">标题</h1></main>')
        revision = self.write(source)
        result = workbench.promote_identities(self.file, [{"tag": "h1", "path": [0, 0]}], revision)
        self.assertFalse(result["changed"])
        self.assertFalse(result["assigned"][0]["created"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), source)

    def test_generated_ids_never_collide(self):
        revision = self.write(page(
            '<main><p class="row">一</p><p class="row">二</p><p class="row">三</p></main>'
        ))
        result = workbench.promote_identities(self.file, [
            {"tag": "p", "path": [0, 0]},
            {"tag": "p", "path": [0, 1]},
            {"tag": "p", "path": [0, 2]},
        ], revision)
        values = [item["identity"]["value"] for item in result["assigned"]]
        self.assertEqual(len(set(values)), 3)
        self.assertEqual(values[0], "row")

    def test_generated_id_avoids_an_existing_value(self):
        revision = self.write(page('<main><div id="card"></div><p class="card">文</p></main>'))
        result = workbench.promote_identities(self.file, [{"tag": "p", "path": [0, 1]}], revision)
        self.assertNotEqual(result["assigned"][0]["identity"]["value"], "card")

    def test_promoted_element_is_addressable_afterwards(self):
        revision = self.write(page('<main><section><button class="buy">购买</button></section></main>'))
        result = workbench.promote_identities(self.file, [{"tag": "button", "path": [0, 0, 0]}], revision)
        identity = result["assigned"][0]["identity"]
        source = self.file.read_text(encoding="utf-8")
        node = resolve(source, {"tag": "button", "identity": identity})[2]
        self.assertEqual(node.attrs["class"], "buy")

    def test_attribute_lands_inside_a_void_element_tag(self):
        revision = self.write(page('<main><img src="a.png" alt="图"></main>'))
        workbench.promote_identities(self.file, [{"tag": "img", "path": [0, 0]}], revision)
        source = self.file.read_text(encoding="utf-8")
        self.assertIn('<img src="a.png" alt="图" data-wb-id=', source)

    def test_attribute_lands_before_a_self_closing_slash(self):
        revision = self.write(page('<main><img src="a.png" /></main>'))
        workbench.promote_identities(self.file, [{"tag": "img", "path": [0, 0]}], revision)
        source = self.file.read_text(encoding="utf-8")
        self.assertRegex(source, r'<img src="a\.png" data-wb-id="[^"]+" />')

    def test_multiple_insertions_do_not_corrupt_each_other(self):
        revision = self.write(page(
            '<main><h2 class="a">甲</h2><h2 class="b">乙</h2><h2 class="c">丙</h2></main>'
        ))
        workbench.promote_identities(self.file, [
            {"tag": "h2", "path": [0, 0]},
            {"tag": "h2", "path": [0, 1]},
            {"tag": "h2", "path": [0, 2]},
        ], revision)
        source = self.file.read_text(encoding="utf-8")
        self.assertIn('<h2 class="a" data-wb-id="a">甲</h2>', source)
        self.assertIn('<h2 class="b" data-wb-id="b">乙</h2>', source)
        self.assertIn('<h2 class="c" data-wb-id="c">丙</h2>', source)
        # The document must still parse into the same shape.
        parser, body = tree(source)
        self.assertEqual(len(workbench.structural_children(workbench.node_at_path(body, [0]))), 3)

    def test_stale_revision_is_refused_without_touching_the_file(self):
        source = page('<main><p class="x">文</p></main>')
        self.write(source)
        with self.assertRaises(workbench.WorkbenchError) as caught:
            workbench.promote_identities(self.file, [{"tag": "p", "path": [0, 0]}], "0" * 64)
        self.assertEqual(caught.exception.code, "REVISION_CONFLICT")
        self.assertEqual(self.file.read_text(encoding="utf-8"), source)

    def test_slug_falls_back_to_the_tag_name(self):
        revision = self.write(page("<main><blockquote>引用</blockquote></main>"))
        result = workbench.promote_identities(self.file, [{"tag": "blockquote", "path": [0, 0]}], revision)
        self.assertEqual(result["assigned"][0]["identity"]["value"], "blockquote")

    def test_slug_drops_stopwords_and_stays_short(self):
        self.assertEqual(workbench.slugify("The Quick Brown Fox And The Lazy Dog", "x"), "quick-brown-fox-lazy")
        self.assertEqual(workbench.slugify("!!!", "fallback"), "fallback")
        self.assertTrue(workbench.WB_ID_PATTERN.match(workbench.slugify("Hero Title 2024", "x")))


class RealisticPageTests(unittest.TestCase):
    """End-to-end against the repository's own demo page."""

    @classmethod
    def setUpClass(cls):
        cls.source = (PROJECT_ROOT / "tests" / "fixtures" / "sample.html").read_text(encoding="utf-8")

    def test_every_element_round_trips_through_its_path(self):
        parser, body = tree(self.source)
        elements = [node for node in parser.nodes if node.is_inside(body) and node.tag != "script"]
        self.assertGreater(len(elements), 60)
        for node in elements:
            path = workbench.node_path(node, body)
            self.assertIsNotNone(path)
            self.assertIs(workbench.node_at_path(body, path), node)

    def test_every_description_snippet_matches_the_source_exactly(self):
        parser, body = tree(self.source)
        for node in parser.nodes:
            if not node.is_inside(body) or node.tag == "script":
                continue
            item = workbench.describe_anchor(parser, body, node)
            if item["snippetTruncated"]:
                continue
            self.assertEqual(self.source[item["startOffset"]:item["endOffset"]], item["snippet"])

    def test_line_numbers_agree_with_the_files_own_lines(self):
        parser, body = tree(self.source)
        lines = self.source.splitlines()
        for node in parser.nodes:
            if not node.is_inside(body) or node.tag == "script":
                continue
            item = workbench.describe_anchor(parser, body, node)
            self.assertGreaterEqual(item["lineStart"], 1)
            self.assertLessEqual(item["lineEnd"], len(lines))
            self.assertIn(f"<{node.tag}", lines[item["lineStart"] - 1])

    def test_nav_link_selection_pulls_its_own_rules_only(self):
        parser, body = tree(self.source)
        node = next(item for item in parser.nodes if item.attrs.get("class") == "nav-links")
        rules = workbench.related_css(parser, self.source, [node], workbench.document_css_rules(self.source))
        selectors = [rule["selector"] for rule in rules]
        self.assertTrue(any(".nav-links" in item for item in selectors))
        self.assertFalse(any(item == ".code-block" for item in selectors))

    def test_deeply_nested_leaf_is_still_uniquely_addressable(self):
        parser, body = tree(self.source)
        node = next(item for item in parser.nodes if item.tag == "figcaption")
        path = workbench.node_path(node, body)
        resolved = workbench.resolve_anchor(parser, body, {"tag": "figcaption", "path": path})
        self.assertIs(resolved, node)


if __name__ == "__main__":
    unittest.main()
