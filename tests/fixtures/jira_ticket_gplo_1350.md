## Contexto / Problema

Los tickets GPLO deben seguir una estructura fija —**plan de prueba A/B/C** + **métricas y tipos de métrica**— que hoy depende de disciplina manual y driftea. Queremos **obligar** a esa estructura en **cada creación de ticket**, con enforcement por capas, e implementarlo como parte del **ai-playbook** (el framework que gobierna _cómo_ se trabaja). Este ticket **dogfoodea** su propia estructura.

## Alcance / Entregables

0. **Taxonomía canónica (bloqueante)**: fijar la estructura obligatoria del ticket + la **lista cerrada de tipos de métrica** (p.ej. cobertura/compliance · calidad/exactitud · tendencia/burn-down · rendimiento/eficiencia · coste). Reconstruida desde el audit de taxonomía 2026-08-01 → **confirmar con Arturo**.
1. **Template canónico** en el ai-playbook = fuente de verdad de la estructura.
2. **Regla dura en** `AGENTS.md` (+ rule spec en `.ai-playbook/docs/rules/`) que vincula a **todo agente**: no emitir ticket sin A/B/C + métricas.
3. **Skill** `/jira-ticket` que construye el ticket desde el template y **se niega** a emitirlo si falta cualquier sección obligatoria.
4. **Validador (ratchet)**: script que consulta tickets abiertos vía Jira API y reporta los no-conformes (exit≠0 / informe periódico).
5. **Backstop Jira** (humanos-en-UI): Automation _validate-on-create_ (auto-comenta lo que falta + flag `Needs-Triage`); opcionalmente **campos custom requeridos** como hard-gate en la pantalla de creación.

## Plan de prueba (A/B/C)

* **A — baseline / happy path**: crear un ticket vía el skill con todas las secciones → éxito, template renderizado completo; el validador lo marca **conforme**.
* **B — cambio / control negativo**: ticket al que le falta una sección obligatoria → el skill lo **rechaza**; un ticket sembrado no-conforme en Jira → la Automation lo flaggea y el validador sale **≠0**. (Prueba que el gate **falla de verdad**, no que "parece" pasar — control negativo.)
* **C — regresión**: sobre el corpus de tickets **ya-conformes**, el validador da **0 falsos positivos**; los legacy no-conformes se listan sin romper la ejecución.

## Métricas (métrica → tipo)

* **% de tickets nuevos conformes** (objetivo 100% por el camino agente) → _cobertura / compliance_.
* **Tasa de falsos positivos del validador** → _calidad / exactitud_.
* **Nº de tickets abiertos no-conformes en el tiempo** (burn-down) → _tendencia_.
* **Δ tiempo de creación con skill vs manual** → _rendimiento / eficiencia_ (el gate no debe penalizar el flujo).

## Prerrequisitos / Notas

* **Cross-repo**: el grueso vive en **ai-playbook** (template + rule + skill + validador); GPLO sólo **trackea** este item.
* GPLO es **team-managed** → los campos custom requeridos (capa 1) tienen límites; la Automation (capa 2) es el backstop realista para humanos-en-UI.
* Épica provisional **Platform (GPLO-1100)** por ser tooling/gates; **movible** si se crea una épica de proceso/gobernanza del playbook.
* Origen: sesión de migración CX53 (2026-08-02), pregunta de Arturo "cómo obligamos a la estructura de tickets".
