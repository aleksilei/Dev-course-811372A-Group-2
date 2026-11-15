// Loads the control panel's browser scripts (cloud/static/app.js, then
// stakeholders.js, as index.html does) into a Node vm context with a stand-in
// page, so tests can call their functions without a browser and without
// changing the scripts.

import fs from 'node:fs';
import vm from 'node:vm';

const STATIC = new URL('../../../../cloud/static/', import.meta.url);
const SCRIPTS = ['app.js', 'stakeholders.js'];

function element(tag = 'div') {
  return {
    tag,
    value: '',
    textContent: '',
    className: '',
    hidden: false,
    children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {},
    classList: { toggle() {} },
  };
}

export function loadPanel() {
  const elements = new Map();
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
      querySelectorAll: () => [],
    },
    window: { location: { hash: '' }, addEventListener() {} },
    // The scripts fetch the API when they load: never answer.
    fetch: () => new Promise(() => {}),
    setInterval() {},
    URLSearchParams,
    Option: function Option(text, value) { this.text = text; this.value = value; },
    console,
  });
  for (const name of SCRIPTS) {
    vm.runInContext(fs.readFileSync(new URL(name, STATIC), 'utf8'), context, { filename: name });
  }
  return {
    // A top-level function or constant of the scripts, by name.
    get: (name) => vm.runInContext(name, context),
    context,
  };
}

// Values from the scripts' context have that context's Object and Array, which
// assert.deepStrictEqual tells apart from this one's: compare plain copies.
export const plain = (value) => JSON.parse(JSON.stringify(value));
