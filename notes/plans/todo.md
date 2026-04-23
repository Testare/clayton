# TODO

- [ ] optimize machete_all: BFS explores a very large state space for pokemon with low flee rates, producing thousands of paths. Investigate pruning strategies (e.g. ignore paths dominated by shorter ones, cap per-depth count) after validating the base implementation.
