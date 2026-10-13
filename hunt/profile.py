import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from hunt.models import Profile
from hunt.ports import Assessor

COMMENT = re.compile(r"(?<!\\)%.*")
HREF = re.compile(r"\\href\{[^}]*\}\{([^}]*)\}")
DROP_WITH_ARG = re.compile(r"\\(?:vspace|hspace|raisebox|begin|end|label|usepackage|documentclass|setlength|addtolength|renewcommand|newcommand)\*?(?:\[[^\]]*\])?\{[^}]*\}")
COMMAND = re.compile(r"\\[a-zA-Z]+\*?|\\[ ,;!/]")
MATH = re.compile(r"\$[^$]*\$")
ESCAPES = {r"\%": "%", r"\&": "&", r"\$": "$", r"\_": "_", r"\#": "#", "{,}": ",", r"\\": " ", "~": " "}


def latex_to_text(tex: str) -> str:
    body = tex.split(r"\begin{document}", 1)[-1].split(r"\end{document}", 1)[0]
    body = COMMENT.sub("", body)
    for k, v in ESCAPES.items():
        body = body.replace(k, v)
    body = HREF.sub(r"\1", body)
    body = DROP_WITH_ARG.sub(" ", body)
    body = MATH.sub(lambda m: m.group(0).strip("$"), body)
    body = COMMAND.sub(" ", body)
    body = body.replace("{", " ").replace("}", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    return re.sub(r"\n{2,}", "\n\n", "\n".join(lines)).strip()


def ensure_profile(session: Session, user_id: str, llm: Assessor, tex_path: Path) -> Profile:
    text = latex_to_text(Path(tex_path).read_text())
    version = hashlib.sha1(text.encode()).hexdigest()[:8]
    row = session.get(Profile, user_id)
    if row and row.resume_version == version:
        return row
    out = llm.extract_profile(text)
    if row is None:
        row = Profile(user_id=user_id)
        session.add(row)
    row.resume_version, row.resume_text, row.skills = version, text, out.skills
    row.years_experience, row.updated_at = out.years_experience, datetime.now(UTC)
    session.flush()
    return row
