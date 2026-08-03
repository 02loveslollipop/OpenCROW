print("== RSA small-root starter ==")

# Toy setup for experimentation with small_roots().
# Replace n, beta, bounds, and the polynomial with challenge-specific values.
n = 101 * 113
R.<x> = PolynomialRing(Zmod(n))

secret = 12
f = x - secret
target = f.monic()

roots = target.small_roots(X=2^8, beta=0.5)
print(f"roots = {roots}")

# Typical pattern:
# 1. Build f(x) over Zmod(n)
# 2. Encode the unknown small value as x
# 3. Tune X and beta to the instance
# 4. Verify recovered roots against the original relation
