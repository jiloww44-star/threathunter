# Drill 02 — Halt the swarm

**Objective:** prove you can stop running automation *and* that you believe
the safety copy only after testing it. ~5 min.

## Setup

1. Ops Node → submit goal: `Sweep our whole IoT estate for the top
   exploitable CVEs` (fan-out ≈ PENTEST_SUITE — enough tasks to interrupt).
2. At the Plan Review gate, note the agent chain and any cost warning —
   then **Approve & Execute**.

## Steps

1. While tasks are still PENDING/RUNNING, press **⏸ Halt Swarm** on the tree
   header and confirm with the verbatim dialog.
2. Inspect the task list: running tasks reach a safe point; pending tasks
   flip to HALTED_BY_USER. The tree reads HALTED.
3. Read the system's message about rollback *word by word*.

## Expected honest behavior to recognize

- Halt is cooperative drain at safe points — not a violent mid-write kill;
  the UI says exactly that.
- Completed work is **not rolled back**; if you want it gone, the delete
  control (🗑) is a separate, explicit action — and it says deletion is
  permanent.
- The halt itself is a `halt_requested` entry in the safety-events KPI and
  on the Data Stream (PERSISTED) — control actions are auditable.

## Pass condition (self-judged)

You can state what happened to (a) the running task, (b) the two pending
tasks, (c) the already-written findings — without re-reading this page.
