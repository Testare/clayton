# 9. Troubleshooting

## Seed A won't narrow to one candidate

**Several candidates left, nothing eliminating them.** Keep listening for Elm calls — each one
roughly halves the field. If the roamer routes are all `.`, fill them in; they cut a lot.

**No candidates at all.** You're outside the search window, or something was mistyped. Widen
**± seconds** and **± delays** and re-check the roamer order — it's Raikou, Entei, then
Latias/Latios, and getting it wrong eliminates everything.

**Never the seed you aimed at.** If you're consistently off by a similar amount, that's
calibration, not bad luck — see below.

## Seed B won't narrow, or has no candidates

**Empty from the first character.** The search is centred where your model predicts Seed B
lands. On a fresh profile that's the Standard model, which is not your hardware — widen
**± delays** substantially, or calibrate first.

**Emptied partway through.** Most likely a mistyped character. `u` undoes the last one. Check
you're using the right letter for what you saw — the **?** button shows the exact in-game
messages for your species.

**Still empty after widening.** Use **Widen search window**, which also drops the probability
cap that `± delays` alone doesn't touch.

## "No metang frame in range"

The in-house frame search can't find your species in the searched window. In order of
likelihood:

1. **Block scores are wrong or too low** — [page 7](07-safari-blocks.md). This is the usual
   cause
2. **Wrong area** for the species
3. **Wrong time of day** — your target's hour puts you in a bucket where it doesn't appear
4. The frame genuinely sits beyond the search range — raise it in Preferences

## The frame guide says I've overshot

You advanced past the target frame. There's no way back — the RNG only moves forward. Reset
and run it again.

To avoid it: let the Elm calls carry the last few advances rather than flipping right up to
the target, and watch the guide string.

## My Δ delay values are all large

Systematically off in the same direction means the model's intercept is wrong for your current
setup. Common causes:

- Calibrated on a different console, or with a different flashcart
- Using the bundled **Standard** model rather than your own
- Timer stages 1 or 2 changed since you calibrated

Refit. If it persists, check whether your runs are clustered at one Vector ms — a fit needs
spread to find the slope.

## Rank targets is slow

The first rank on a chart is around 35 seconds and shows progress. After that it's cached to
disk and instant, including across restarts.

If it's recomputing every time, something in the key is changing between runs — most likely
you're switching active calibration models back and forth. One report is cached per
expedition+chart, so alternating between two models pays the sweep each time.

## Probabilities dropped after recalibrating

Expected, and usually honest. A better-fitted model with a realistic jitter gives lower, truer
numbers than an optimistic one. A saved target's frozen `P(success)*` is from when you saved
it — **Examine** re-scores it live.

## Windows: "Argument 'picture' must be a picture that can be used as a Icon"

A pywebview bug rather than anything wrong with your setup — its Windows backend extracts the
window icon from `sys.executable`, and the API it uses returns a bogus-but-nonzero value when
that file has no icon, which pywebview doesn't check for. Store-installed Pythons trigger it
most often.

Fixed in Clayton — update to the latest commit. See
[BUILDING-WINDOWS.md](../packaging/BUILDING-WINDOWS.md) for detail.

## Windows: "Failed to resolve Python.Runtime.Loader.Initialize"

The downloaded build is still marked as blocked. Windows tags files extracted from an
internet-downloaded `.zip` as untrusted, and .NET refuses to load its component while that tag
is there. In PowerShell, from the folder holding `Clayton.exe`:

```powershell
Get-ChildItem -Recurse | Unblock-File
```

Builds you compiled yourself never hit this.

## The app won't start

**Linux:** a blank window is usually the WebKitGTK renderer; Clayton already sets
`WEBKIT_DISABLE_DMABUF_RENDERER=1`, but a stale environment can override it.

**Windows:** almost always the missing WebView2 runtime — see
[BUILDING-WINDOWS.md](../packaging/BUILDING-WINDOWS.md).

## Where is my data?

| Platform | Location |
|---|---|
| Linux | `~/.local/share/Clayton` |
| Windows | `%LOCALAPPDATA%\Clayton` |
| macOS | `~/Library/Application Support/Clayton` |

Profiles, expeditions, runs and charts live there, outside the app. Rebuilding never touches
them. **Export** (profile bundle or expedition) is the portable way to move between machines.
