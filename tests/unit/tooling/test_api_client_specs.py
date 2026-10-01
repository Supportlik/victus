"""T-TOOL-103: every public ApiClient method is named by a web spec; T-TOOL-104: the parser.

``web/src/app/api/api-client.ts`` is the one place the web app talks to the API. A method
that no spec names can send the wrong path, drop a query parameter or lose its body, and
nothing notices until a person does. This check reads the public methods of the
``ApiClient`` class and fails, naming the method, when no ``*.spec.ts`` under ``web/src``
refers to it.

What counts as a method: a member declared at the top level of the ``ApiClient`` class body
whose name is followed (optionally after a type parameter list) by ``(``. The constructor,
members marked ``private``, ``protected`` or ``static``, and ``#private`` members are skipped;
so are fields (``readonly http = inject(...)`` has ``=`` before any ``(``). Strings, template
literals (including ``${...}``), and comments are skipped while the braces are counted, so a
``{`` inside a string or a template never shifts the depth.

What counts as a reference, in any ``*.spec.ts`` under ``web/src``:

* a member call ``.name(`` (optionally with whitespace before ``(``), as in
  ``api.createProduct(...)`` or ``a.createProduct(...)`` in a table row; or
* the name as a complete quoted literal, ``'name'``, ``"name"`` or ```name```, as in
  ``vi.spyOn(api, 'createProduct')`` or a table row ``{ name: 'createProduct', ... }``.

A bare identifier or an object key (``{ createProduct: vi.fn() }`` in a stubbed client) is not a
reference: a stub replaces the method rather than checking what it sends. The check is a floor,
not a proof: a reference says some spec names the method, and the spec says what it checks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.domain

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "web" / "src" / "app" / "api" / "api-client.ts"
SPECS = ROOT / "web" / "src"

_MEMBER = re.compile(
    r"(?P<mods>(?:(?:public|private|protected|static|readonly|async|override|get|set)\s+)*)"
    r"(?P<name>#?[A-Za-z_$][\w$]*)\s*(?:<[^()]*?>)?\s*(?P<next>[(=:;?!])"
)
_SKIPPED_MODIFIERS = {"private", "protected", "static"}


def _class_body(source: str, class_name: str) -> str:
    """The text between the braces of ``class <class_name>``, strings and comments included."""
    match = re.search(rf"\bclass\s+{re.escape(class_name)}\b[^{{]*\{{", source)
    if not match:
        raise ValueError(f"class {class_name} not found")
    start = match.end()
    end = _matching_brace(source, start)
    return source[start:end]


def _skip_string(source: str, i: int) -> int:
    """Index just past the quoted string starting at ``source[i]`` (``'`` or ``"``)."""
    quote = source[i]
    i += 1
    while i < len(source):
        if source[i] == "\\":
            i += 2
            continue
        if source[i] == quote or source[i] == "\n":
            return i + 1
        i += 1
    return i


def _skip_template(source: str, i: int) -> int:
    """Index just past the template literal starting at ``source[i]``; ``${...}`` nests."""
    i += 1
    while i < len(source):
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if source.startswith("${", i):
            i = _matching_brace(source, i + 2) + 1
            continue
        i += 1
    return i


def _skip_comment(source: str, i: int) -> int | None:
    """Index just past a comment starting at ``i``, or None when there is none."""
    if source.startswith("//", i):
        nl = source.find("\n", i)
        return len(source) if nl < 0 else nl
    if source.startswith("/*", i):
        close = source.find("*/", i + 2)
        return len(source) if close < 0 else close + 2
    return None


def _matching_brace(source: str, i: int) -> int:
    """Index of the ``}`` that closes the block whose body starts at ``i``."""
    depth = 0
    while i < len(source):
        c = source[i]
        after_comment = _skip_comment(source, i)
        if after_comment is not None:
            i = after_comment
        elif c in "'\"":
            i = _skip_string(source, i)
        elif c == "`":
            i = _skip_template(source, i)
        elif c == "{":
            depth += 1
            i += 1
        elif c == "}":
            if depth == 0:
                return i
            depth -= 1
            i += 1
        else:
            i += 1
    raise ValueError("unbalanced braces")


def _top_level_statements(body: str) -> list[str]:
    """Code of the class body at nesting depth zero, one chunk per member start.

    Everything inside ``{...}``, ``(...)``, strings and comments is dropped, so what remains are
    member heads such as ``private readonly http = inject`` or ``health(): Observable<Health>``.
    """
    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(body):
        c = body[i]
        after_comment = _skip_comment(body, i)
        if after_comment is not None:
            i = after_comment
            continue
        if c in "'\"":
            i = _skip_string(body, i)
            continue
        if c == "`":
            i = _skip_template(body, i)
            continue
        if c in "{(":
            if depth == 0:
                current.append(c)
            depth += 1
        elif c in "})":
            depth -= 1
            if depth == 0 and c == "}":
                chunks.append("".join(current))
                current = []
        elif depth == 0:
            if c == ";":
                chunks.append("".join(current))
                current = []
            else:
                current.append(c)
        i += 1
    chunks.append("".join(current))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def public_methods(source: str, class_name: str = "ApiClient") -> list[str]:
    """Public method names of ``class_name`` in declaration order (see the module docstring)."""
    names: list[str] = []
    for chunk in _top_level_statements(_class_body(source, class_name)):
        match = _MEMBER.match(chunk)
        if not match or match.group("next") != "(":
            continue
        name = match.group("name")
        mods = set(match.group("mods").split())
        if name == "constructor" or name.startswith("#") or mods & _SKIPPED_MODIFIERS:
            continue
        names.append(name)
    return names


def is_referenced(name: str, spec_source: str) -> bool:
    """Whether a spec names the method by a member call or as a complete quoted literal."""
    ident = re.escape(name)
    call = rf"\.\s*{ident}\s*\("
    quoted = rf"(['\"`]){ident}\1"
    return re.search(call, spec_source) is not None or re.search(quoted, spec_source) is not None


def test_t_tool_103_every_api_client_method_is_named_by_a_spec() -> None:
    """T-TOOL-103: each public ApiClient method is referenced by some ``*.spec.ts``."""
    methods = public_methods(CLIENT.read_text(encoding="utf-8"))
    assert len(methods) > 50, f"the parser found only {methods}"
    specs = [p.read_text(encoding="utf-8") for p in SPECS.rglob("*.spec.ts")]
    missing = [m for m in methods if not any(is_referenced(m, s) for s in specs)]
    assert not missing, "ApiClient methods no spec names:\n  " + "\n  ".join(missing)


SNIPPET = """
import { x } from 'y';

function helper(a: string): string { return a; }

/** A client. */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  readonly base = '/api/v1';
  #secret = 1;
  static create(): ApiClient { return new ApiClient(); }

  constructor(private readonly other: Other) {}

  // notAMethod(): commented out
  /* alsoNot(x) { } */
  health(): Observable<Health> {
    return this.http.get<Health>(`${API_BASE}/health`);
  }
  products(q: string, opts: { limit?: number; on?: string | null } = {}): Observable<Product[]> {
    const nested = { inner(): void {} };
    return this.http.get(`/p/${opts.limit ?? `${'{'}`}`, { params: params({ q }) });
  }
  typed<T>(
    id: number,
  ): Observable<T> {
    const brace = '{ not(a) method }';
    return this.http.get<T>(`/x/${id}`);
  }
  async load(): Promise<void> {}
  private hidden(): void {}
  protected guarded(): void {}
  #really(): void {}
  public last(): string { return "}"; }
}

export class Other {
  outside(): void {}
}
"""


def test_t_tool_104_the_parser_reads_public_methods_only() -> None:
    """T-TOOL-104: fields, constructor, private/protected/static/# members, nested functions,
    and names inside strings, templates or comments are not methods; the reference rule accepts
    ``.name(`` and quoted names and rejects bare identifiers and object keys."""
    assert public_methods(SNIPPET) == ["health", "products", "typed", "load", "last"]

    assert is_referenced("createProduct", "api.createProduct({ name: 'Oats' })")
    assert is_referenced("createProduct", "a . createProduct ()")
    assert is_referenced("createProduct", "vi.spyOn(api, 'createProduct')")
    assert is_referenced("createProduct", '{ name: "createProduct", call }')
    assert not is_referenced("createProduct", "{ createProduct: vi.fn() }")
    assert not is_referenced("createProduct", "createProduct(x)")
    assert not is_referenced("product", "api.products('q')")
    assert not is_referenced("product", "'products'")
    assert not is_referenced("me", "api.meal()")
