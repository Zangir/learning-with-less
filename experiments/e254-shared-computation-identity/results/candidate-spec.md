# E-254 candidate specification and exact-check contract

Operation D031:T012:concrete-algorithm-or-identity. Recorded before executing checks. The target is one reusable service-envelope compiler, not a fitted experiment or performance benchmark.

## Candidate and observation contract

Fix a retrospective, discrete, single-price-level tape X of N unit decrements from initial depth D. Initial ahead volume a0 belongs to a supplied finite set A0; behind volume is D-a0. Each hidden decrement is a trade T, an ahead cancellation Ca, or a behind cancellation Cb. T removes ahead first; when ahead is zero it removes behind and contributes one unit to virtual executable service S. Ca/Cb require positive volume in their compartment. No adds, repricing, hidden liquidity, participant inference, quote removal or endogenous reaction is modeled. A stipulated terminal number K of trades is supplied to both methods; it is not recovered from the anonymous tape. The full feasible set H(X) consists of all legal labelings/initial allocations satisfying that terminal restriction.

A fixed protected shadow probe is placed at the declared initial queue boundary. S_t(h) is potential service under this frozen exogenous tape, and fill for size v is min(v,S_t(h)). This is a defined shadow-service accounting functional, not a proved causal finite-order fill counterfactual: inserting a real order could alter subsequent trades, cancellations and priority. The toy unit is synthetic volume, not an exchange contract or asset quantity. The tape is already complete when compiled, so the result is a retrospective conditional certificate, not a live fill forecast or an executable trading decision.

Primary exact fixture: D=N=4, A0={1,2}, K=3. Other prespecified checks address empty support, forced trades/terminal viability, a singleton path and all cancellations. No random generator or fitted model is used; seed 20260919 is reserved but not consumed.

## Query schedule, target and validity

First freeze X, constraints and H(X); then compile once; then reveal any finite sequence of queries q=(t,v,g,c), where t is a retained horizon, v>0, c is a constant crossing loss, and g is nondecreasing on [0,1]. Query choices may depend on previous answers, but may not change the initial queue boundary, tape, constraints or action feedback. A changed observation contract requires rebuilding or correctly updating the object and charging that cost.

Post loss: L_post(h,q)=g((v-min(v,S_t(h)))/v). Cross loss: L_cross(h,q)=c. Target: minimize worst-case loss over H(X), with exact ties resolved to cross. This is robust loss, not expected utility or minimax regret. The primary test grid uses t=0..4, v in {1,2,3}, g(x) in {x,x*x,1[x>0]}, and c in {1/4,1/2,3/4}. Fractions are exact; there are 135 fixed query combinations. This finite grid checks implementation; the proof covers every admissible g,v,c.

Contract: if the realized history h* belongs to the nonempty H(X), then every reported upper loss bound holds for h*, for all admissible queries simultaneously, hence also after arbitrary adaptive selection from that fixed family. This is deterministic containment conditional on modeling assumptions, not a 95% coverage statement. No claim is made that an empirical history actually belongs to H(X). A realized-history set is not a confidence region for its conditional law. The optional all-distributions-supported-on-H interpretation produces the same robust-loss maximum because point masses are allowed, but is an additional worst-case decision convention, not inferred probabilities or calibrated ambiguity.

## Reusable object and direct comparator

Cache m_t=min_{h in H(X)} S_t(h). Monotonicity and finiteness imply max_h L_post(h,q)=g((v-min(v,m_t))/v), attained by a minimum-service witness. The crossing bound is c. The same vector is therefore the exact direct risk-certificate basis.

Build a layered DAG with full future-sufficient queue state z=(t,a,b,k), where k is used trade count. All edge constraints and terminal feasibility depend on z, not accumulated service. Backward traversal marks nodes that reach an allowed terminal (t=N,k=K). Forward min-plus relaxation computes d(z), the least accumulated service among prefixes reaching z. Then m_t is the least d(z) among backward-viable nodes at layer t. Reject empty support rather than inventing a bound. A prefix with larger service at the same full state can be discarded for this monotone single-horizon target because its continuations are identical; merging on service alone is unsafe.

Executable pseudocode:

```
G = legal_queue_DAG(X, initial_ahead_set, terminal_trade_count)
viable = backwards_reachable_from_valid_terminals(G)
if no initial node is viable: return INVALID_CONTRACT
cost[initial_nodes] = 0
for each layer in chronological order:
    for each legal edge u -> v with service_increment w:
        cost[v] = min(cost[v], cost[u] + w)
    m[layer] = min(cost[v] for viable v in this layer)
return m

answer(t, size, g, cross_cost):
    post_bound = g(1 - min(size, m[t]) / size)
    return post if post_bound < cross_cost else cross
```

The restoration route may keep G or enumerate all feasible histories for interpretation, but it can use exactly this compiler. The direct route receives the same full DAG state, constraints and tools and can keep m. A naive per-query reconstruction or direct solver repeats avoidable work; neither is the fair comparator. Potential savings versus that naive route are known shared compilation: reuse transitions, terminal viability and min-plus reductions. No operation has yet been identified that restoration can save and the matched direct compiler cannot.

## Operation and cost accounting

Let V,E be reachable DAG nodes/edges, N retained horizons, and Q revealed queries. Explicit DAG construction, backward viability and forward extrema each require O(V+E) graph operations; retained graph storage O(V+E), envelope O(N). Envelope-only retention is permitted after compilation for both methods if updates/witnesses are not required. Answer cost is O(1)+cost(g) per query, with exact-number bit costs shared. Full history enumeration may be exponential in tape length, and the state graph may also grow substantially as constraints are enriched. These are structural bounds, not measured runtime or a universal lower bound. Query-dependent constraints or coupled/nonmonotone losses require richer objects or new optimization on both sides.

There is no learning, tuning, calibration, rich-row relabeling or sampling in this exact candidate; those costs are zero because absent, not omitted. Constraint discovery and acquisition are not performed; supplied model assumptions are explicit external inputs, not free scientific knowledge. Both sides receive identical assumptions and would pay equally for any future discovery, data preparation, updates or validation. Construction, solver passes, storage and full query evaluation are charged to both. With one cheap query, compilation/storage need not repay their cost; a simple direct bound can be preferable. No fitted experiment, runtime comparison, training uncertainty interval or performance margin is authorized or warranted if the identity holds.

## Prespecified boundary checks

1. Exhaustively enumerate the tiny fixtures independently of the DAG transition function; compare minima/maxima, robust bounds, exact ties and actions using rational arithmetic.
2. A forced-trades fixture must expose incorrect prefix minima when terminal viability is ignored.
3. Distinct finished response signatures (0,2) and (1,1) show coordinate minima (0,1) need not be jointly attainable. For a sum of unit shortfalls from target2 at two horizons, true worst loss is2 while the compressed profile yields3. This is an algebraic fixture, not a claimed queue history or market row.
4. For post-versus-cross minimax regret, a lower envelope alone is insufficient; the upper service envelope also matters for crossing regret. This distinct objective is only a boundary check.
5. A singleton equal mixture over services0 and2 (size2, crossing loss1/2) has distribution-specific best expected action loss1/2. Expected hindsight best-action loss is1/4. Conflating the two comparators changes regret; no posterior or empirical distribution is fitted.

A passed check is software/algebra evidence only. The conclusion sought is an exact mapping and known-method reduction, not a positive or negative measured learning result.

## Accepted-context corrections

R021/RV019 are accepted by D031 as targeted negative novelty evidence, not failure/impossibility. Preserve their frozen artifacts; apply the correction here: imputation/prediction gains are more consistently correlated for generated linear outcomes, not uniformly larger effects. R016 is accepted under D026 only for controlled/conditional scope:966 sufficient count-free explanations and13 cases not certified by those bounds; necessity of richer reasoning is not proved. Mandatory original Q16/Q17/Q18 participant-data replications remain open. No E210r2 outcome is reopened and no E205 realistic simulator completion is claimed.
