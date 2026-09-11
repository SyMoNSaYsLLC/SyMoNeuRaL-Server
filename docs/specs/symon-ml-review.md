# Review: the SyMoN_ML blueprint and the TRON licensing PoC

Sources, both in `references/` and gitignored:
`SyMoN_ML (1).pdf` (15pp, engineering blueprint) and `Projects_Crypto/TRX_POC (1).pdf`
(1pp, licensing PoC — byte-identical to `reading/TRX_POC (9).pdf`, so there is only one
version of it despite the two filenames). Context comes from Garrett's pivot email,
also at `reading/Gmail - Infrastructure Pivot_*.pdf`.

**This is a review, not a state document.** See `README.md` in this directory. Nothing here
has been implemented, and two findings below argue that part of it should not be implemented
as written.

---

## 1. The DRM fails open. This is the finding that matters.

`auth_daemon.py`, as written in Part 9:

```python
def verify_tron_subscription(self) -> bool:
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            ...
            for tx in data.get("data", []):
                if tx.get("to") == self.node_wallet and tx.get("confirmed", False):
                    self.is_licensed = True
                    return True

        # Fallback for localized offline testing / sandbox execution
        if self._check_local_sandbox_state():
            self.is_licensed = True
            return True
    except Exception as e:
        print(f"[SyMoNeuRaL Auth] Network state verification warning: {e}")
    return self.is_licensed

def _check_local_sandbox_state(self) -> bool:
    # Allows local zero-internet execution during private staging/benchmarking
    return True
```

`_check_local_sandbox_state` returns `True` unconditionally, and it is reached whenever the
TRON lookup does not produce a match. So the licence check passes when:

- the TRON API is unreachable (`iptables -A OUTPUT -d api.trongrid.io -j DROP`)
- the network cable is unplugged
- trongrid returns a non-200, or rate-limits
- DNS fails
- the wallet has never received a payment at all

**The entire IP moat is bypassed by denying the licensing server, which is the one action an
unlicensed user is most obviously motivated to take and the easiest to perform.** A licence
check must fail closed: if the state cannot be verified, the answer is no.

The `except` branch compounds it — it returns `self.is_licensed`, which the fallback has
already set to `True` on any prior call in the same process.

Related, smaller, still real:

- **The transaction test is `tx.get("to") == self.node_wallet and tx.get("confirmed")`.** It
  does not check the amount, the sender, the token contract, or the timestamp. Any confirmed
  TRC-20 transfer to that wallet, of any token, of any size, at any time in the past, grants
  a permanent licence. One transfer of 1 sun licenses a customer forever, and so does a
  transfer of an unrelated airdropped token.
- **`is_licensed` is cached on the instance and never re-checked or expired.** A subscription
  that lapses stays valid for the life of the process.

## 2. The key exchange is not designed, and may not be designable as described

`unlock_encrypted_adapter(self, encrypted_symon_path, master_key)` takes the key **as an
argument**. So at the moment of decryption the key is already on the customer's machine. The
comment says "In production, this key is retrieved via the TRON TVM daemon", but:

- **A blockchain is a public ledger.** A decryption key placed on-chain is readable by
  everyone. The key cannot live in the contract.
- If the key comes from a server we run, then that server is the licence authority and the
  blockchain is doing no security work — it is a payment rail, which is a perfectly good
  thing to be, but it is not the moat.
- Whatever fetches the key must authenticate as the licensed customer, and that credential
  is on the customer's machine too. The problem recurses.

## 3. Client-side DRM has a structural ceiling, and the pitch overstates it

The weights must be plaintext in RAM for the GPU to use them, on hardware the customer owns
and roots. `gdb`, `/proc/<pid>/mem`, or a `PeftModel.from_pretrained` hook recovers them.

The precise claim in the email is defensible: *"Even if a competitor copies the entire server
hard drive, they get useless encrypted data."* That is true, and encryption at rest is worth
doing. The claim it is used to support — that competitors "won't be able to" replicate the
setup — is not. Client-side DRM raises effort; it does not prevent copying. Every media DRM
scheme with vastly more engineering behind it has been broken the same way.

Recommend keeping the at-rest encryption and the payment rail, and describing them as what
they are, because the honest version is still a good product story: encrypted at rest, keyed
to an active subscription, with tamper effort that exceeds the value for most customers.

## 4. The blueprint is superseded by what this repo already does

It is a plan for a machine this one no longer is. Building to it would be a regression:

| Blueprint | This repo |
|---|---|
| `transformers` + `bitsandbytes` 4-bit NF4 | llama.cpp, GGUF **Q4_K_M**, measured **80–92 tok/s** |
| `main.py` FastAPI gateway on `127.0.0.1:8800` | `backend/server.py`, already exactly that |
| `symon_ml/training/tuner.py` QLoRA | `training/train_lora.py`, adapter already built |
| `~/AI_Local_NVIDIA/llm/…` | `/home/google/Symoneural/…`, and nothing hardcodes its path |
| `pip install torch --index-url …/cu121` | **cu128 — cu121 does not support Blackwell sm_120** |

That last row is not a style difference. Following Part 2 verbatim installs a torch that
cannot run on this card. `.claude/HANDOVER.md` §8 is explicit: the training venv is cu128
because sm_120 requires it.

The genuinely new material in the blueprint is Parts 7, 9 and 10 — encryption, the auth
daemon, key exchange. Parts 1–6 and 8 describe an inference and tuning stack that exists here
in a faster form.

## 5. The Akash figure has an unstated assumption

From the email: an A100 80GB at **~$1.68/hour**, and an 8-GPU node generating **~$5,800 per
month**.

```
1.68 × 8 × 24 × 30 = $9,676.80    at 100% utilisation
5,800 / 9,676.80   = 59.9%        implied utilisation
```

The $5,800 is a reasonable number *and it embeds a ~60% utilisation assumption that the
document never states*. In a pitch, that is the number a sceptical reader attacks first, and
"we assumed 60% occupancy" is a much stronger answer given up front than extracted under
questioning. The $1.68/hr is a **market rate** — vendor, not measured, and it moves.

Under this project's own labelling rule these are **projected** figures resting on a
**vendor** rate. Neither is measured here, and no A100 exists on this box.

## 6. What was built in response

`backend/apps/gateway/` and `/gateway.html` — the licensing surface, listed on the rack,
reporting `offline`, because there is no contract, no wallet, no daemon and no key material
on this machine. It carries no fee figures: prices are quoted, not published, and a licensing
page is the worst possible place to break that rule.

**Not built, deliberately:** the auth daemon and the DRM wrapper. Finding 1 means implementing
Part 9 as written would ship a licence check that grants access to anyone who blocks a domain,
while the surface around it claims the weights are protected. That is worse than having no
DRM, because it is a false assurance. It needs a fail-closed redesign and a real answer to
finding 2 first.
