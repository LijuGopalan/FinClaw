## 2026-07-07 - Frontend Array O(N*P) Bottlenecks
**Learning:** In frontend chart rendering, `calculateSMA` was repeatedly calling `data.slice(...).reduce(...)` inside a loop causing O(N*P) complexity (N=data length, P=period). The JS engines choke on this when charts have long history buffers.
**Action:** Always prefer an O(N) iterative sliding window when summing over a moving window to avoid expensive array slicing/allocations in JS loops.
