print("== RSA Boneh-Durfee starter ==")

# Setup scaffold for low private exponent attacks.
# Replace with challenge-specific n, e, and parameter choices.
p = next_prime(2^31)
q = next_prime(2^32)
n = p * q
phi = (p - 1) * (q - 1)
d = 2^12 + 1
e = inverse_mod(d, phi)

delta = log(d, n).n()
print(f"n_bits = {n.nbits()}")
print(f"d = {d}")
print(f"delta_approx = {delta}")
print(f"bd_condition = {delta < 0.292}")

A = (n + 1) // 2
R.<x, y> = PolynomialRing(ZZ)
f = 1 + x * (A + y)

print(f"polynomial = {f}")
print("Use this as the starting polynomial setup before building the lattice basis.")

# This template intentionally stops before basis construction.
# Tune m, t, X, and Y to the specific instance before attempting LLL.
