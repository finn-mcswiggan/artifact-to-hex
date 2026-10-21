// Render a Hex app element tree to plain text without a DOM, for logic checks in node.
//
//   import { React } from "./_data.js";
//   import { renderText } from "./walk.mjs";
//   import { MyView } from "./views/MyView.js";
//   globalThis.HEX_INPUTS = { selected_account: "acme-001" };
//   const { text, options } = renderText(React.createElement(MyView));
//   if (!text.includes("Total revenue £1.2m")) throw new Error("KPI tile drifted");
//
// Function components are called (hooks are synchronous stubs, effects never run), host elements
// contribute their text children. `options` collects <option> labels so dropdown contents can be checked.
export function renderText(root) {
  const out = [], options = [], errors = [];
  function walk(el) {
    if (el == null || el === false || el === true) return;
    if (Array.isArray(el)) return el.forEach(walk);
    if (typeof el !== "object") { out.push(String(el)); return; }
    if (typeof el.type === "function") {
      try { return walk(el.type({ ...el.props, children: el.children })); }
      catch (e) { errors.push(`${el.type.name || "component"}: ${e.message}`); return; }
    }
    if (el.type === "option") options.push((el.children || []).join(""));
    (el.children || []).forEach(walk);
  }
  walk(root);
  return { text: out.join(" ").replace(/\s+/g, " ").trim(), options, errors };
}

// Convenience: assert a substring is present, printing context when it is not.
export function expectText(text, needle, label = needle) {
  if (text.includes(needle)) { console.log(`ok   ${label}`); return true; }
  console.log(`FAIL ${label}: "${needle}" not found`);
  process.exitCode = 1;
  return false;
}
