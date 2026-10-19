# SAT/Max-SAT Encoding Experiments

This repository contains the implementation, experimental results, and figure-generation script for comparing different encodings of at-most-one constraints in the allocation problem using SAT/Max-SAT.

## Experimental Objective

The experiment compares three encodings:

- **Pairwise**
- **Sequential Counter**
- **Cardinality Network**

All three configurations use the same RC2 MaxSAT solver with the `g3` backend. The experiment focuses on the effect of the at-most-one constraint encoding on formula size, model-generation time, and solving performance.

## Experimental Setup

The allocation problem contains \(n\) tasks and \(n\) processors. Each assignment has an integer cost generated uniformly between 1 and 10.

The experiment uses the following settings:

| Parameter | Value |
|---|---|
| Problem sizes (\(n\)) | 25, 40, 50, 60, 65, 100 |
| Instances per size | 10 |
| Encodings | Pairwise, Sequential Counter, Cardinality Network |
| Solver | RC2 |
| Solver backend | `g3` |
| Timeout per run | 300 seconds |
| Base random seed | `20260101` |
| Python version | 3.13.3 |
| python-sat version | 1.9.dev14 |

Each instance is evaluated using all three encodings, resulting in 180 runs.

The random seeds are derived from the base seed, problem family, problem size, and instance index so that the encodings can be compared on the same generated instances.

## Repository Contents

- `run_experiments.py`: Runs the experiments and records their results.
- `make_figures.py`: Generates PDF figures from the experiment CSV file.
- `results_alloc_300/`: Contains the allocation experiment results and environment metadata.
- `figures/`: Contains the generated PDF figures.

The results directory includes `results.csv` and `environment.json`. The latter records the software environment, hardware information, solver settings, random seed, and package versions.

## Requirements

Python 3.13.3 and the `python-sat` package version used in the experiments are documented in the environment metadata.

Install the dependencies listed in `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

## Running the Allocation Experiment

Run the following command from the repository root:

```bash
python run_experiments.py --families allocation --sizes-allocation 25 40 50 60 65 100 --instances 10 --timeout 300 --max-cost 10 --out results_alloc_300
```

The output directory is specified by `--out`. The experiment script records the results and environment information in that directory.

## Generating the Figures

After the experiment CSV file has been generated, run:

```bash
python make_figures.py results_alloc_300/results.csv
```

The script generates two PDF figures:

- `allocation_clause_count.pdf`: Total number of clauses for each encoding and problem size.
- `allocation_solve_time.pdf`: Mean solving time over solved instances only.

The solving-time figure excludes timed-out runs. The experiment results also include the information needed to analyze solver performance while accounting for timeouts.

If the generated PDFs are stored in the repository's `figures/` directory, move them there after generation or update the output paths in the script accordingly.

## Reported Allocation Results

The reported experiment contains 180 runs:

- 174 runs completed within the timeout.
- 6 runs timed out.
- All 6 timeouts occurred in instances 0 and 1 at problem size \(n=50\), across all three encodings.

For \(n=100\), the pairwise encoding generated 1,000,100 clauses, compared with 69,300 for the sequential counter and 128,500 for the cardinality network.

These results apply to the tested allocation formulation, generated instances, solver configuration, and experimental environment. They should not be interpreted as a general ranking of encodings for all Max-SAT problems.

## Reproducibility

The repository provides the experiment script, generated results, environment metadata, and figure-generation script to support inspection and reproduction of the reported experiments.

The environment metadata records the Python and `python-sat` versions, hardware and platform information, solver configuration, random seed, and package versions.
