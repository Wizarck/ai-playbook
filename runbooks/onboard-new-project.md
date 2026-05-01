# runbook: onboard-new-project.md — anexar un repo nuevo al playbook

> **Audience**: tú o un teammate que acaba de crear (o va a crear) un repo nuevo y quiere que herede del ai-playbook (Hindsight memory loop, MCP config, SessionStart hook, propagation auto-bump, runbooks compartidos, **Profile A/B release-management v0.8.x**).
> **Status**: v1.1.0 (2026-05-01 — adds Profile A/B project board bootstrap + AI-reviewer install + visibility decision).
> **Prereqs**: `git`, `python 3.11+`, `pre-commit` (`pipx install pre-commit`), `gh` autenticado, acceso de escritura al repo nuevo + al ai-playbook.
> **Tiempo estimado**: 10–15 minutos en el happy path (Profile A consumers add ~5min for CodeRabbit install).

## Qué hace este runbook

Un comando ➜ un consumer completamente onboarded:
- Submódulo `.ai-playbook/` pinneado al último release.
- `AGENTS.md` (v1 dispatcher), `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/00-dispatcher.mdc` (routers).
- `mcp-servers.project.yaml` con bank Hindsight asignado.
- `.claude/settings.json` con SessionStart hook auto-fired.
- `.mcp.json` + `.gemini/settings.json` rendered desde el merge 3-layer.
- `.gitignore` extendido con entries del playbook.
- Pre-commit hooks instalados (schema, secrets, verdict, drift checks).
- `~/.ai-playbook/projects.yaml` actualizado para resolución de paths local.
- Fila en `<playbook>/consumers.yaml` para que la propagation Action auto-bumpea el submódulo en cada release nuevo.

Después del runbook, una sesión Claude Code en ese repo:
1. Auto-recall desde Hindsight bank `<project>` al arrancar.
2. Reconoce los specs universales via inheritance.
3. Recibe bumps automáticos cuando el playbook saca v0.x.y.

## Decisiones previas

### ¿bank name?

Default = `<project-name>` lowercased. Coincide con la convención de [memory-hierarchy.md §2](../specs/memory-hierarchy.md). Si tu proyecto necesita un bank distinto (p.ej. compartir bank con otro proyecto), cambia el `--bank-id` a la mano en `mcp-servers.project.yaml` y `.claude/settings.json` después del bootstrap.

### ¿Profile A (Public OSS) o Profile B (Private Solo)? (per [release-management.md §5.6](../specs/release-management.md))

Decide ANTES del bootstrap — afecta enforcement (branch protection, CodeRabbit, merge queue) y rollout.

| Visibility | Profile | Plan GH | Branch protection | CodeRabbit | Merge queue |
|---|---|---|---|---|---|
| `public` | A | Free OK | ✅ | ✅ free unlimited | ✅ |
| `private` | B | Free OK | ❌ (need Pro/Team) | ❌ (paid only) | ❌ |
| `private` | A | Pro/Team ($4+/mes) | ✅ | ❌ (paid only) | ✅ Team+ |

**Regla práctica**:
- Si el repo es OSS-friendly (license Apache/MIT/AGPL, no IP secret) → **público + Profile A**. Coste 0, full enforcement.
- Si privacidad es no-negociable y eres solo tú trabajando → **privado + Profile B** (convention-based, sin gates duros).
- Si privacidad + multi-dev → **privado + Pro/Team + Profile A**.

Documentar la decisión en `docs/hitl-gates-log.md` del consumer.

## Steps

### 1. Crea el repo en GitHub (si aún no existe)

```bash
gh repo create Wizarck/<project-name> --private --clone
cd <project-name>
git commit --allow-empty -m "chore: initial commit"
git push -u origin master
```

Si el repo ya existe + tiene historia, cd a su working tree y salta a step 2.

### 2. Corre bootstrap.py desde el playbook

Un solo comando, cubre TODO:

```bash
cd /c/Projects/<project-name>          # tu repo nuevo

python /c/Projects/ai-playbook/scripts/bootstrap.py <project-name> \
    --owner <your-email> \
    --path . \
    --register-in /c/Projects/ai-playbook \
    --visibility private \
    --default-branch master
```

**Flags clave:**

| Flag | Qué hace |
|---|---|
| `<project-name>` (positional) | Slug. `[a-zA-Z0-9][a-zA-Z0-9_-]*`. Bank será `<project-name>` lowercased. |
| `--owner` | Email para AGENTS.md frontmatter. Default: `$GIT_AUTHOR_EMAIL` o `git config user.email`. |
| `--path .` | Donde escribir. Default: `<cwd>/<project-name>` (asume target NO existe). Pasa `.` cuando el repo ya existe. |
| `--register-in <playbook-path>` | Añade automáticamente la fila a `consumers.yaml` del playbook. Si lo omites, lo haces a mano (paso 4 abajo). |
| `--visibility private\|public` | Para la fila en consumers.yaml. Si es público, ten en cuenta que `.mcp.json` no incluirá la personal layer. |
| `--default-branch master\|main` | Branch principal del repo (afecta consumers.yaml y la propagation Action). |
| `--personal` | Solo para repos personales de Arturo. Marca `personal: true` en frontmatter; carga ELIGIA.md como add-on. |
| `--dry-run` | Simula sin escribir. Recomendado primer pasada. |

**Output esperado:**

```
→ Bootstrapping project '<project-name>'
   target : /c/Projects/<project-name>
   owner  : <your-email>
   pin    : v0.3.0
   mode   : live
✓ added .ai-playbook submodule pinned at v0.3.0
✓ copied 8 templates with placeholder substitution
✓ pre-commit installed
✓ doctor.py: ✅ healthy
✓ rendered .mcp.json + .gemini/settings.json for <project-name>
✓ added <project-name> row to /c/Projects/ai-playbook/consumers.yaml
  Next: cd /c/Projects/ai-playbook && git add consumers.yaml && git commit && git push

✅ Bootstrap complete. Next steps:
   1. cd /c/Projects/<project-name>
   2. Fill placeholders in AGENTS.md (§1 identity, §3 active work, §4 rules).
   ...
```

### 3. Edita los placeholders manuales en AGENTS.md

Bootstrap deja 4 placeholders sin substituir (son human-fill obligatorios):

```bash
grep -nE "\{\{[A-Z_]+\}\}" AGENTS.md
```

| Placeholder | Qué pones |
|---|---|
| `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}` | §1 identity. Qué ES el proyecto en 1-3 líneas. |
| `{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}` | §3 active work. `none (bootstrap)` está bien al arrancar. |
| `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}` | §4 hard rules. Reglas TUYAS, no las del playbook. |
| `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}` | §7 overrides. `None.` por default. |
| `{{EMPTY_FILL_AS_YOU_LEARN}}` | §8 gotchas. Vacío por default. |

Valida:

```bash
python .ai-playbook/scripts/schema_validate.py AGENTS.md
# Expected: ✅ AGENTS.md valid against schema agents-md/v1
```

### 4. Si NO usaste `--register-in`: añade la fila a mano

Edita `<playbook>/consumers.yaml`:

```yaml
consumers:
  # ... existentes ...
  <project-name>:
    repo: Wizarck/<project-name>
    default_branch: master
    visibility: private
    status: active
    notes: <one-line description>.
```

### 5. Commit + push del proyecto

```bash
cd /c/Projects/<project-name>
git add .
git commit -m "chore: bootstrap <project-name> via ai-playbook v0.3.0"
git push
```

### 6. Commit + push del playbook (consumers.yaml updated)

```bash
cd /c/Projects/ai-playbook
git add consumers.yaml
git commit -m "feat(consumers): onboard <project-name>"
git push
```

A partir de aquí, **cada vez que el playbook saque un release nuevo (`v0.X.Y` tag)**, la GH Action `propagate-playbook-bump.yml` abre automáticamente un PR en `Wizarck/<project-name>` actualizando el submódulo. Solo hay que merger el PR.

### 7. (NEW v0.8.x) Bootstrap del GH Project board + Profile A/B enforcement

Crea el GH Project (si aún no existe):

```bash
gh project create --owner Wizarck --title "<project-name>"
gh project list --owner Wizarck   # toma el número resultante (e.g. 5)
```

Si vas a usar Jira en lugar de GH Issues como tracker, igualmente crea el Project para el roadmap visual + el `Status` schema canónico.

Luego corre el bootstrap (idempotente — safe re-run):

```bash
cd /c/Projects/<project-name>
python -m scripts.bootstrap_gh_project \
    --owner Wizarck --project-number <N> \
    --repo Wizarck/<project-name> \
    --profile auto \
    --visibility private   # solo si NO está aún seteado
```

`--profile auto` detecta visibility con `gh repo view` y aplica:
- **Profile A (public)**: branch protection clásico (1 review, 5 universal checks), repo settings (auto-merge=on, squash-only, delete-branch-on-merge), `.coderabbit.yaml` desde template.
- **Profile B (private)**: solo repo settings + emite notice de que branch protection no está disponible en GH Free private.

En ambos profiles se añade el schema canónico al project: Status (5 opciones) + Risk + P&L impact + Branch + Base SHA.

### 8. (NEW v0.8.x — Profile A only) Instala CodeRabbit GH App

Solo para consumers públicos. CodeRabbit es free unlimited en repos OSS y revisa cada PR con las path-instructions de `.coderabbit.yaml`.

1. Ve a https://github.com/marketplace/coderabbitai
2. "Set up plan" → "CodeRabbit Free for Open Source"
3. Account: **Wizarck** · Repository access: **"Only select repositories"** → marca el nuevo repo
4. "Install & Authorize"

Cuando llegue el primer PR, CodeRabbit comenta automáticamente. **Importante**: el worker AI debe leer + responder a sus comentarios antes de pedir Gate F (per [release-management.md §4.5](../specs/release-management.md)).

Si el repo seguirá privado o no quieres CodeRabbit: skip este paso. El contrato §4.5 degrada a self-review (Profile B fallback).

### 9. (NEW v0.8.x — Profile A only) Configura el secret `ELIGIA_GOD_MODE`

Si el consumer tiene CI workflows que necesitan clonar `.ai-playbook/` (submodule privado de `Wizarck/ai-playbook`), añade el PAT:

```bash
gh secret set ELIGIA_GOD_MODE -R Wizarck/<project-name> --body "<your-pat>"
```

El PAT necesita scope `Contents: read` sobre `Wizarck/ai-playbook` + `Wizarck/eligia-skills`. Sin esto, `actions/checkout@v4` con `submodules: true` falla con 404 "Repository not found".

### 10. Verifica el SessionStart hook

Lanza una sesión Claude Code en el directorio:

```bash
cd /c/Projects/<project-name>
claude  # o lo que uses para arrancar Claude Code
```

Después de ~30-60 segundos (cold recall) debería aparecer `.claude/injected-context.md` con resultados del bank `<project-name>`. Es normal que esté vacío en la primera ejecución (el bank se crea lazy).

### 11. (Opcional, v0.8.x) Copia los workflow templates de auto-transition + dep-check

Si el consumer va a usar el slicing graph activamente (Wave 0 sequential + Wave N parallel), copia los workflows que automatizan el board:

```bash
cp .ai-playbook/templates/new-project/.github/workflows/project-status.yml.tmpl \
   .github/workflows/project-status.yml
cp .ai-playbook/templates/new-project/.github/workflows/dep-check.yml.tmpl \
   .github/workflows/dep-check.yml
```

Configura los secrets/variables que requieren:
- Secret `PROJECT_AUTOMATION_TOKEN`: PAT con Project read+write.
- Variable `PROJECT_OWNER`: `Wizarck`.
- Variable `PROJECT_NUMBER`: `<N>` del paso 7.

`project-status.yml` auto-transiciona items de Blocked → Todo cuando sus deps están Done (per [release-management.md §6.3](../specs/release-management.md)). `dep-check.yml` (opt-in hard gate) bloquea PR de slice X si las deps no están Done aún.

## Manual override del SOPS path

Si tu repo NO está al lado de `eligia-core/` (donde viven las CF Access creds del Hindsight), edita `.claude/settings.json` y cambia:

```diff
- "command": "sops exec-env ../eligia-core/secrets/secrets.env -- python ..."
+ "command": "sops exec-env /absolute/path/to/your/secrets.env -- python ..."
```

O usa env vars exportadas en tu shell profile y elimina el `sops exec-env` wrapper.

## Verificación end-to-end

```bash
# Schema
python .ai-playbook/scripts/schema_validate.py AGENTS.md

# MCP config
python .ai-playbook/scripts/mcp/validate.py --consumer-root .

# Drift check (legacy ↔ v1 yamls)
python .ai-playbook/scripts/check_mcp_drift.py --consumer-root .

# Doctor (full suite)
python .ai-playbook/scripts/doctor.py
```

Los 4 deberían terminar en ✅. Si alguno falla, su `FIX:` line dice exactamente qué hacer.

## Rollback

Si algo sale mal y quieres deshacer:

```bash
cd /c/Projects/<project-name>
git rm -rf --cached .ai-playbook
rm -rf .ai-playbook AGENTS.md CLAUDE.md GEMINI.md .claude .cursor .mcp.json .gemini mcp-servers.project.yaml

# Si .gitignore tenía entries del playbook que quieres mantener, edita a mano
# antes de borrar el archivo entero.

# Y si registraste en consumers.yaml:
cd /c/Projects/ai-playbook
# borra la fila a mano + commit
```

## Cross-references

- [`scripts/bootstrap.py`](../scripts/bootstrap.py) — el script principal (paso 2).
- [`scripts/bootstrap_gh_project.py`](../scripts/bootstrap_gh_project.py) — Profile A/B + project board (paso 7).
- [`scripts/opsx_apply_companion.py`](../scripts/opsx_apply_companion.py) — Branch+SHA + pre-flight rebase para `/opsx:apply` (per release-management.md §6.5).
- [`templates/new-project/`](../templates/new-project/) — los archivos copiados.
- [`templates/new-project/.coderabbit.yaml.tmpl`](../templates/new-project/.coderabbit.yaml.tmpl) — Profile A AI-reviewer config (auto-copiado por bootstrap).
- [`templates/new-project/.github/workflows/project-status.yml.tmpl`](../templates/new-project/.github/workflows/project-status.yml.tmpl) — auto-transition Blocked→Todo (paso 11).
- [`templates/new-project/.github/workflows/dep-check.yml.tmpl`](../templates/new-project/.github/workflows/dep-check.yml.tmpl) — opt-in dep-graph enforcement (paso 11).
- [`consumers.yaml`](../consumers.yaml) — registro de consumers (alimenta la propagation Action).
- [`specs/release-management.md`](../specs/release-management.md) — Profile A/B + AI-reviewer §4.5 + §6.5 pre-flight rebase.
- [`runbooks/release.md`](release.md) — cuando el playbook corte un nuevo release, los consumers reciben PRs auto.
- [`runbooks/hindsight-retain.md`](hindsight-retain.md) — cómo guardar lessons al bank del proyecto.
- [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) §2 — convención de bank names.
- [`docs/session-start-hook.md`](../docs/session-start-hook.md) — wiring del hook + degradation path.
