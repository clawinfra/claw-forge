# Solidity LSP — solc + slither

## What this skill does
Compiles Solidity contracts with `solc` and runs security analysis with `slither` to catch vulnerabilities before deployment.

## Installation check
```bash
solc --version
slither --version
```
If not installed:
```bash
# solc compiler
npm install -g solc

# slither security analyser
pip install slither-analyzer

# Or with uv
uv tool install slither-analyzer
```

## Type checking / diagnostics
```bash
# Compile a single contract (outputs ABI + bytecode)
solc --abi --bin contracts/MyContract.sol

# Compile with optimiser
solc --optimize --optimize-runs 200 --abi --bin contracts/MyContract.sol

# Security analysis — human-readable summary
slither . --print human-summary

# Full slither report
slither contracts/MyContract.sol

# Slither on a Hardhat or Foundry project
slither . --hardhat-ignore-compile   # if Hardhat already compiled
slither . --foundry-ignore-compile   # if Foundry already compiled
```
Output means:
- `HIGH` → critical vulnerability, must fix before deploy
- `MEDIUM` → significant risk, fix before deploy
- `LOW` → minor issue, review and decide
- `INFO` → informational, no action required

## Key flags
| Flag | Purpose |
|------|---------|
| `--abi` | Output contract ABI |
| `--bin` | Output compiled bytecode |
| `--optimize` | Enable Yul optimiser |
| `--optimize-runs 200` | Optimise for average call count (200 = standard) |
| `--print human-summary` | Slither: show contract summary table |
| `--json -` | Slither: machine-readable JSON to stdout |
| `--exclude-dependencies` | Slither: skip node_modules/lib contracts |

## Config file
Hardhat (`hardhat.config.js`):
```javascript
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: { optimizer: { enabled: true, runs: 200 } }
  }
};
```

Foundry (`foundry.toml`):
```toml
[profile.default]
src = "src"
out = "out"
libs = ["lib"]
optimizer = true
optimizer_runs = 200
solc_version = "0.8.24"
```

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `Source file requires different compiler version` | Pragma mismatch | Match solc version to pragma or update pragma |
| `Undeclared identifier` | Variable/function not in scope | Fix import or identifier name |
| `TypeError: Type X not implicitly convertible` | Type mismatch | Add explicit cast or fix type |
| `Reentrancy` (slither HIGH) | State change after external call | Use checks-effects-interactions pattern |
| `Unchecked transfer` (slither MEDIUM) | ERC20 return value ignored | Wrap in `require(token.transfer(...))` or use SafeERC20 |
| `Suicidal` (slither HIGH) | `selfdestruct` accessible | Remove or gate behind multi-sig |

## Integration with agent workflow
1. After writing or modifying `.sol` files, run `solc --abi --bin <file>` to confirm compilation.
2. Run `slither . --exclude-dependencies` for security analysis.
3. Fix all `HIGH` findings before any deploy or audit.
4. Fix `MEDIUM` findings before mainnet deploy.
5. Re-run slither after fixes to confirm clean: `slither . --exclude-dependencies 2>&1 | grep -E "HIGH|MEDIUM"` should be empty.
