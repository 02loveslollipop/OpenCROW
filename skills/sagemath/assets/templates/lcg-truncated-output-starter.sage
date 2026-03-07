print("== LCG truncated output starter ==")

modulus = 2^16
a = 11035
c = 12345
seed = 4242
shift = 8

def step(x):
    return (a * x + c) % modulus

x0 = seed
x1 = step(x0)
x2 = step(x1)

y0 = x0 >> shift
y1 = x1 >> shift
y2 = x2 >> shift

candidates = []
for low in range(2^shift):
    guess = (y0 << shift) + low
    if (step(guess) >> shift) == y1 and (step(step(guess)) >> shift) == y2:
        candidates.append(guess)

print(f"observed = {[y0, y1, y2]}")
print(f"candidate_count = {len(candidates)}")
print(f"seed_recovered = {seed in candidates}")
print(f"candidates = {candidates[:8]}")

# Scale this by combining more observations or expressing low bits as unknowns in modular equations.
