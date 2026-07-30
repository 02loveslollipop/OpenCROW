print("== Lattice LLL starter ==")

q = 101
a = 37
b = 12

M = Matrix(ZZ, [
    [q, 0, 0],
    [a, 1, 0],
    [b, 0, 1],
])

print("basis =")
print(M)
print("lll =")
print(M.LLL())

# Replace the basis with challenge-specific coefficients.
