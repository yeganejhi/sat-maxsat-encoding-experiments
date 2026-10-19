#!/usr/bin/env python3
"""
Encoding-comparison experiment for Weighted Partial Max-SAT (PySAT + RC2).

Compares three at-most-one encodings (pairwise, sequential counter,
cardinality network) on two problem families (allocation, scheduling),
with the solver (RC2, backend g3) held fixed.

Every (family, size, instance, encoding) run happens in a fresh subprocess
so a hard timeout can be enforced and memory is released between runs.
Results are appended to results/results.csv; an interrupted run can be
resumed by re-running the same command.

Usage:
    python run_experiments.py --quick          # tiny smoke test
    python run_experiments.py                  # full experiment (defaults)
    python run_experiments.py --families allocation --timeout 300
"""
import argparse, csv, json, math, multiprocessing as mp, os, platform
import random, subprocess, sys, time
from pathlib import Path

BASE_SEED = 20260101                       # change only if you want new instances
ENCODINGS = ["pairwise", "seqcounter", "cardnetwrk"]
DEFAULT_SIZES = {
    "allocation": [10, 20, 40, 60, 80, 100],   # n tasks = n processors
    "scheduling": [5, 10, 15, 20, 25, 30],     # n tasks on one machine
}
PREC_P = 0.10          # probability of a precedence relation between a pair
HORIZON_FACTOR = 1.3   # T_max = ceil(1.3 * sum of durations)
SOLVER_BACKEND = "g3"  # SAT oracle used inside RC2 (fixed for all runs)

FIELDS = ["family", "size", "instance", "seed", "encoding",
          "n_vars", "n_clauses", "n_hard", "n_soft", "n_enc_clauses",
          "gen_time", "solve_time", "total_time", "status", "objective", "valid"]


def instance_seed(family, size, idx):
    return f"{BASE_SEED}-{family}-{size}-{idx}"       # str seeds are deterministic


def make_instance(family, size, idx, cost_max=100):
    rng = random.Random(instance_seed(family, size, idx))
    if family == "allocation":
        return {"n": size,
                "cost": [[rng.randint(1, cost_max) for _ in range(size)] for _ in range(size)]}
    d = [rng.randint(1, 5) for _ in range(size)]
    order = list(range(size))
    rng.shuffle(order)                                  # hidden topological order
    prec = [(order[a], order[b]) for a in range(size) for b in range(a + 1, size)
            if rng.random() < PREC_P]
    return {"n": size, "d": d, "T": math.ceil(HORIZON_FACTOR * sum(d)), "prec": prec}


def amo(lits, enc, wcnf, vpool):
    """Add an at-most-one constraint with the chosen encoding; return #clauses."""
    from pysat.card import CardEnc, EncType
    kinds = {"pairwise": EncType.pairwise,
             "seqcounter": EncType.seqcounter,
             "cardnetwrk": EncType.cardnetwrk}
    if len(lits) < 2:
        return 0
    cnf = CardEnc.atmost(lits=lits, bound=1, vpool=vpool, encoding=kinds[enc])
    wcnf.extend(cnf.clauses)
    return len(cnf.clauses)


def build_allocation(inst, enc):
    from pysat.formula import WCNF, IDPool
    n, c = inst["n"], inst["cost"]
    wcnf, vpool = WCNF(), IDPool()
    x = {(i, j): vpool.id(("x", i, j)) for i in range(n) for j in range(n)}
    k = 0
    for i in range(n):
        row = [x[i, j] for j in range(n)]
        wcnf.append(row)                                # at least one processor
        k += amo(row, enc, wcnf, vpool)                 # at most one processor
    for j in range(n):
        k += amo([x[i, j] for i in range(n)], enc, wcnf, vpool)
    for i in range(n):
        for j in range(n):
            wcnf.append([-x[i, j]], weight=c[i][j])
    return wcnf, x, k


def build_scheduling(inst, enc):
    from pysat.formula import WCNF, IDPool
    n, d, T, prec = inst["n"], inst["d"], inst["T"], inst["prec"]
    wcnf, vpool = WCNF(), IDPool()
    times = {i: range(0, T - d[i] + 1) for i in range(n)}
    x = {(i, t): vpool.id(("x", i, t)) for i in range(n) for t in times[i]}
    k = 0
    for i in range(n):                                  # exactly one start time
        lits = [x[i, t] for t in times[i]]
        wcnf.append(lits)
        k += amo(lits, enc, wcnf, vpool)                # <- encoding under test
    for (i, j) in prec:                                 # i finishes before j starts
        for t in times[i]:
            for tp in times[j]:
                if tp < t + d[i]:
                    wcnf.append([-x[i, t], -x[j, tp]])
    for i in range(n):                                  # no overlap on one machine
        for kk in range(i + 1, n):
            for t in times[i]:
                for tp in times[kk]:
                    if t < tp + d[kk] and tp < t + d[i]:
                        wcnf.append([-x[i, t], -x[kk, tp]])
    for i in range(n):                                  # minimise sum of start times
        for t in times[i]:
            if t > 0:
                wcnf.append([-x[i, t]], weight=t)
    return wcnf, x, k


BUILD = {"allocation": build_allocation, "scheduling": build_scheduling}


def validate_allocation(inst, x, model, cost):
    n, c = inst["n"], inst["cost"]
    true = set(l for l in model if l > 0)
    assign = {}
    for (i, j), v in x.items():
        if v in true:
            if i in assign:
                return False
            assign[i] = j
    if len(assign) != n or len(set(assign.values())) != n:
        return False
    return sum(c[i][j] for i, j in assign.items()) == cost


def validate_scheduling(inst, x, model, cost):
    n, d, T = inst["n"], inst["d"], inst["T"]
    true = set(l for l in model if l > 0)
    start = {}
    for (i, t), v in x.items():
        if v in true:
            if i in start:
                return False
            start[i] = t
    if len(start) != n:
        return False
    if any(start[i] + d[i] > T for i in range(n)):
        return False
    if any(start[i] + d[i] > start[j] for i, j in inst["prec"]):
        return False
    for i in range(n):
        for k in range(i + 1, n):
            if start[i] < start[k] + d[k] and start[k] < start[i] + d[i]:
                return False
    return sum(start.values()) == cost


VALIDATE = {"allocation": validate_allocation, "scheduling": validate_scheduling}


def worker(conn, family, size, idx, enc, mem_gb, cost_max):
    try:
        if mem_gb:
            try:
                import resource
                lim = int(mem_gb * 1024 ** 3)
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            except Exception:
                pass
        from pysat.examples.rc2 import RC2
        inst = make_instance(family, size, idx, cost_max)  # not timed
        t0 = time.perf_counter()
        wcnf, x, n_enc = BUILD[family](inst, enc)
        gen = time.perf_counter() - t0
        conn.send(("gen", {"n_vars": wcnf.nv, "n_hard": len(wcnf.hard),
                           "n_soft": len(wcnf.soft),
                           "n_clauses": len(wcnf.hard) + len(wcnf.soft),
                           "n_enc_clauses": n_enc, "gen_time": gen}))
        t1 = time.perf_counter()
        with RC2(wcnf, solver=SOLVER_BACKEND) as rc2:
            model = rc2.compute()
            cost = rc2.cost
        solve = time.perf_counter() - t1
        if model is None:
            conn.send(("done", {"solve_time": solve, "status": "unsat",
                                "objective": "", "valid": ""}))
        else:
            ok = VALIDATE[family](inst, x, model, cost)
            conn.send(("done", {"solve_time": solve, "status": "solved",
                                "objective": cost, "valid": int(ok)}))
    except MemoryError:
        conn.send(("error", "memout"))
    except Exception as e:                              # report, never crash the driver
        conn.send(("error", f"error:{type(e).__name__}:{e}"[:200]))
    finally:
        conn.close()


def run_one(family, size, idx, enc, timeout, gen_limit, mem_gb, cost_max):
    ctx = mp.get_context("spawn")
    rx, tx = ctx.Pipe(duplex=False)
    p = ctx.Process(target=worker, args=(tx, family, size, idx, enc, mem_gb, cost_max))
    t_start = time.perf_counter()
    p.start()
    tx.close()
    row = {"family": family, "size": size, "instance": idx,
           "seed": instance_seed(family, size, idx), "encoding": enc,
           "n_vars": "", "n_clauses": "", "n_hard": "", "n_soft": "",
           "n_enc_clauses": "", "gen_time": "", "solve_time": "",
           "total_time": "", "status": "", "objective": "", "valid": ""}
    try:
        if not rx.poll(gen_limit):
            row["status"] = "gen_timeout"
        else:
            kind, payload = rx.recv()
            if kind == "error":
                row["status"] = payload
            else:
                row.update(payload)
                t_gen_done = time.perf_counter()
                if rx.poll(timeout):
                    kind, payload = rx.recv()
                    if kind == "error":
                        row["status"] = payload
                    else:
                        row.update(payload)
                else:
                    row["status"] = "timeout"
                    row["solve_time"] = timeout
                    _ = t_gen_done
    except EOFError:
        row["status"] = "crashed(memout?)"
    finally:
        if p.is_alive():
            p.terminate()
            p.join(5)
            if p.is_alive():
                p.kill()
        p.join()
    if row["gen_time"] != "" and row["solve_time"] != "":
        row["total_time"] = float(row["gen_time"]) + float(row["solve_time"])
    return row


def save_environment(out, args, sizes):
    info = {"python": sys.version, "platform": platform.platform(),
            "processor": platform.processor(), "cpu_count": os.cpu_count(),
            "base_seed": BASE_SEED, "encodings": ENCODINGS, "solver": "RC2",
            "solver_backend": SOLVER_BACKEND, "timeout_s": args.timeout,
            "instances_per_size": args.instances, "sizes": sizes,
            "allocation_cost_range": [1, args.max_cost], "prec_p": PREC_P, "horizon_factor": HORIZON_FACTOR}
    try:
        import pysat
        info["python-sat"] = pysat.__version__
    except Exception:
        pass
    try:
        info["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except Exception:
        pass
    for key, cmd in {"lscpu": ["lscpu"], "pip_freeze": [sys.executable, "-m", "pip", "freeze"]}.items():
        try:
            info[key] = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
        except Exception:
            pass
    (out / "environment.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", nargs="+", default=["allocation", "scheduling"],
                    choices=list(DEFAULT_SIZES))
    ap.add_argument("--sizes-allocation", nargs="+", type=int, default=DEFAULT_SIZES["allocation"])
    ap.add_argument("--sizes-scheduling", nargs="+", type=int, default=DEFAULT_SIZES["scheduling"])
    ap.add_argument("--instances", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0, help="solve timeout (s)")
    ap.add_argument("--gen-limit", type=float, default=900.0, help="encoding-generation limit (s)")
    ap.add_argument("--mem-gb", type=float, default=0, help="per-run memory cap (Linux only; 0 = none)")
    ap.add_argument("--max-cost", type=int, default=100,
                    help="allocation costs are uniform integers in [1, MAX_COST]")
    ap.add_argument("--out", default="results")
    ap.add_argument("--quick", action="store_true", help="tiny smoke test")
    args = ap.parse_args()

    sizes = {"allocation": args.sizes_allocation, "scheduling": args.sizes_scheduling}
    if args.quick:
        sizes = {"allocation": [5, 10], "scheduling": [3, 5]}
        args.instances, args.timeout = 2, 30
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    save_environment(out, args, sizes)

    csv_path = out / "results.csv"
    done = set()
    if csv_path.exists():
        with open(csv_path, newline="") as f:
            done = {(r["family"], int(r["size"]), int(r["instance"]), r["encoding"])
                    for r in csv.DictReader(f)}
    new_file = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        for fam in args.families:
            for size in sizes[fam]:
                for idx in range(args.instances):
                    order = ENCODINGS[idx % 3:] + ENCODINGS[:idx % 3]   # rotate to avoid order bias
                    for enc in order:
                        if (fam, size, idx, enc) in done:
                            continue
                        row = run_one(fam, size, idx, enc, args.timeout, args.gen_limit, args.mem_gb, args.max_cost)
                        w.writerow(row)
                        f.flush()
                        print(f"{fam:10s} n={size:<4d} #{idx:<2d} {enc:10s} "
                              f"{row['status']:8s} vars={row['n_vars']} cl={row['n_clauses']} "
                              f"solve={row['solve_time']}", flush=True)


if __name__ == "__main__":
    main()