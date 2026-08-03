print("== ECC starter ==")

p = 9739
F = GF(p)
E = EllipticCurve(F, [497, 1768])
P = E(1804, 5368)
Q = 1337 * P

print(f"curve_order = {E.order()}")
print(f"P_order = {P.order()}")
print(f"Q = {Q}")

# Replace with challenge-specific curve parameters and points.
