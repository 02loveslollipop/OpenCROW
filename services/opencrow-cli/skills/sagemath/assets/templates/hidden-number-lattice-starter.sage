print("== Hidden-number lattice starter ==")

# Toy hidden-number style lattice.
# Replace q, t_i, u_i, and bound with challenge-specific data.
q = 10007
bound = 2^8
t_values = [123, 456, 789]
u_values = [321, 654, 987]

rows = []
for i in range(len(t_values)):
    row = [0] * (len(t_values) + 1)
    row[i] = q
    rows.append(row)

last = list(t_values) + [bound]
rows.append(last)

M = Matrix(ZZ, rows)
print("basis =")
print(M)
print("lll =")
print(M.LLL())

# One common pattern is to fold observed linear relations into the final row
# and use the short vectors to identify the hidden nonce fragment or secret.
