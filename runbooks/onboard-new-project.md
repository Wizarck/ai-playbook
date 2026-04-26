# runbook: onboard-new-project.md — anexar un repo nuevo al playbook

> **Audience**: tú o un teammate que acaba de crear (o va a crear) un repo nuevo y quiere que herede del ai-playbook (Hindsight memory loop, MCP config, SessionStart hook, propagation auto-bump, runbooks compartidos).
> **Status**: v1.0.0 (2026-04-26).
> **Prereqs**: `git`, `python 3.11+`, `pre-commit` (`pipx install pre-commit`), `gh` autenticado, acceso de escritura al repo nuevo + al ai-playbook.
> **Tiempo estimado**: 5–10 minutos en el happy path.

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

## Decisión previa: ¿bank name?

Default = `<project-name>` lowercased. Coincide con la convención de [memory-hierarchy.md §2](../specs/memory-hierarchy.md). Si tu proyecto necesita un bank distinto (p.ej. compartir bank con otro proyecto), cambia el `--bank-id` a la mano en `mcp-servers.project.yaml` y `.claude/settings.json` después del bootstrap.

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
| `--personal` | Solo para repos personales de Arturo. Marca `personal: true` en frontmatter; carga consumer-d.md como add-on. |
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

### 7. Verifica el SessionStart hook

Lanza una sesión Claude Code en el directorio:

```bash
cd /c/Projects/<project-name>
claude  # o lo que uses para arrancar Claude Code
```

Después de ~30-60 segundos (cold recall) debería aparecer `.claude/injected-context.md` con resultados del bank `<project-name>`. Es normal que esté vacío en la primera ejecución (el bank se crea lazy).

## Manual override del SOPS path

Si tu repo NO está al lado de `consumer-d/` (donde viven las CF Access creds del Hindsight), edita `.claude/settings.json` y cambia:

```diff
- "command": "sops exec-env ../consumer-d/secrets/secrets.env -- python ..."
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

- [`scripts/bootstrap.py`](../scripts/bootstrap.py) — el script.
- [`templates/new-project/`](../templates/new-project/) — los archivos copiados.
- [`consumers.yaml`](../consumers.yaml) — registro de consumers (alimenta la propagation Action).
- [`runbooks/release.md`](release.md) — cuando el playbook corte un nuevo release, los consumers reciben PRs auto.
- [`runbooks/hindsight-retain.md`](hindsight-retain.md) — cómo guardar lessons al bank del proyecto.
- [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) §2 — convención de bank names.
- [`docs/session-start-hook.md`](../docs/session-start-hook.md) — wiring del hook + degradation path.
