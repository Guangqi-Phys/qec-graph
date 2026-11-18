"""Native command adapter shared by original and derived isolated builds."""

from dataclasses import dataclass, field
from pathlib import Path
import shutil

from . import sandbox
from .artifacts import pdf_text_pages, pdf_text_hashes


@dataclass
class Build:
    entry: str
    engine: str
    root: Path
    success: bool = False
    steps: list[dict] = field(default_factory=list)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    compatibility: list[dict] = field(default_factory=list)
    convergence: dict = field(default_factory=dict)


def tool(name):
    for directory in (
        "/Library/TeX/texbin",
        "/Library/Developer/CommandLineTools/usr/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
    ):
        path = Path(directory) / name
        if path.is_file():
            return str(path)
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise ValueError(f"Required local tool is unavailable: {name}")


def execute(build: Build, name, command, *, stdin=None, runner=sandbox.run):
    result = runner(build.root, build.root / "project", command, stdin=stdin)
    log = result.pop("log")
    build.artifacts[f"logs/{name}.log"] = log
    result["log"] = f"logs/{name}.log"
    build.steps.append(result)
    return result["exit"] == 0 and not result["timeout"]


def compile_derived(original, tree, directory, support, compiler):
    root = original.root / directory
    root.mkdir()
    return compiler(tree, original.entry, root, engine=original.engine, support=support)


def compare_pdf_text(original, derived, report):
    job = Path(original.entry).stem
    pdfs = [b.root / "project" / (job + ".pdf") for b in (original, derived)]
    try:
        binary = tool("pdftotext")
    except ValueError:
        report["pdf_text"] = "tool_unavailable"
        return
    if not all(p.is_file() for p in pdfs):
        report["pdf_text"] = "pdf_unavailable"
        return
    pages = []
    for index, pdf in enumerate(pdfs):
        output = original.root / ("pdf-text-" + str(index) + ".txt")
        result = sandbox.run(
            original.root,
            original.root,
            [binary, "-enc", "UTF-8", str(pdf), str(output)],
        )
        derived.artifacts[f"logs/pdf-text-{index}.log"] = result.pop("log")
        if result["exit"] != 0 or result["timeout"]:
            report["pdf_text"] = "failed"
            return
        raw = output.read_bytes()
        derived.artifacts[f"files/pdf-text-{index}.txt"] = raw
        pages.append(pdf_text_pages(raw))
    report["pdf_text"] = "equal" if pages[0] == pages[1] else "different"
    report["pdf_text_sha256"] = pdf_text_hashes(pages)
    report["pdf_text_scope"] = (
        "Per-page non-whitespace text equality; not pixel or mathematical equivalence"
    )
