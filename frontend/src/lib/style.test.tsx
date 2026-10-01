import { render } from "@testing-library/react";
import { bareZeros } from "./style";

test("bareZeros writes zero lengths as the reference does (margin:0, padding:0 4px)", () => {
  const { container } = render(
    <p ref={bareZeros} style={{ margin: "0", fontSize: "13px", padding: "0 4px", minWidth: "0" }}>
      x
    </p>,
  );
  expect(container.firstElementChild?.getAttribute("style")).toBe("margin: 0; font-size: 13px; padding: 0 4px; min-width: 0;");
});

test("bareZeros leaves other lengths alone and ignores null", () => {
  const { container } = render(<p ref={bareZeros} style={{ gap: "10px", padding: "20px 4px" }} />);
  expect(container.firstElementChild?.getAttribute("style")).toBe("gap: 10px; padding: 20px 4px;");
  expect(() => bareZeros(null)).not.toThrow();
});
