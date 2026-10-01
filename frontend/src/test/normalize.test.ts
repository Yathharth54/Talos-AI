import { normalizeHtml as n } from "./normalize";

describe("normalizeHtml", () => {
  test("sorts attributes and class tokens", () => {
    expect(n('<li data-node="x" class="node active">a</li>')).toBe(n('<li class="active node" data-node="x">a</li>'));
  });
  test("normalises inline styles", () => {
    expect(n('<div class="stack" style="gap:16px"></div>')).toBe(n('<div style="gap: 16px;" class="stack"></div>'));
    expect(n('<tr style=""></tr>'.replace("tr", "p"))).toBe(n("<p></p>"));
  });
  test("drops empty class", () => {
    expect(n('<tr class=""><td>x</td></tr>'.replace(/tr|td/g, "span"))).toBe(n("<span><span>x</span></span>"));
  });
  test("drops template indentation but keeps real spaces", () => {
    expect(n('<div>\n    <p>a</p>\n  </div>')).toBe(n("<div><p>a</p></div>"));
    expect(n('<span class="tx"> </span>')).not.toBe(n('<span class="tx"></span>'));
    expect(n("<button>All <span>3</span></button>")).not.toBe(n("<button>All<span>3</span></button>"));
  });
  test("keeps newlines inside text", () => {
    expect(n("<span>a\nb</span>")).not.toBe(n("<span>ab</span>"));
  });
  test("ignores control values and the tab indicator's position", () => {
    expect(n('<input id="k" value="secret">')).toBe(n('<input id="k">'));
    expect(n('<textarea id="ask">typed</textarea>')).toBe(n('<textarea id="ask"></textarea>'));
    expect(n('<span class="tab-ind" style="left: 12px; width: 40px;"></span>')).toBe(n('<span class="tab-ind"></span>'));
  });
  test("drops comments and treats boolean attributes the same", () => {
    expect(n("<p hidden><!-- x -->a</p>")).toBe(n('<p hidden="">a</p>'));
  });
  test("parses table rows outside a table", () => {
    expect(n('<tr data-tool="a"><td class="num">1</td></tr>')).toContain('<td class="num">1</td>');
  });
});
