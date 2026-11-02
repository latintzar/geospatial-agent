# Mobile map and chat

Phones show the map across the viewport below the Atelier navigation. **Ask about a place** opens the existing chat in a full-screen native dialog; **Map** returns to the map. The three retained example actions use the original example-mode hook and scorer result. Drafts, messages and layers remain when the dialog closes or the viewport changes.

Desktop keeps the original 400 px chat column next to the map. A single mounted ChatPanel serves both layouts. The composer uses its full width, a 48 px minimum height and a 16 px phone font. Native dialogs provide keyboard focus containment, Escape dismissal and focus restoration. The process drawer also fills phones. Full-screen dialogs follow the VisualViewport height/offset so the composer remains in the visible region as a software keyboard changes it. Chat, layer and navigation actions use 44 px controls, and the layers popover fits the available width.

The model/backend boundary, frozen query allowlist, synthetic result, dependency lock and Atelier navigation hook are unchanged. The phone example-data badge and map attribution use separate horizontal areas; layer counts remain in the layer control.

## Check the built application

```sh
python -m pip install playwright==1.58.0
python -m playwright install chromium
cd frontend
npm ci
NEXT_PUBLIC_EXAMPLE_MODE=true npm run build
cp -r .next/static .next/standalone/.next/static
if [ -d public ]; then cp -r public .next/standalone/public; fi
cd ..
python3 tests/browser_mobile.py --serve-build frontend/.next/standalone
```

To check an owned running preview, use `--base-url` instead of `--serve-build`. The test opens all three actual examples, reads the retained answer, checks the full map/fullscreen chat at 320/390 px, keeps draft/messages across close and desktop resize, tests the process dialog and native layer controls, and fences model/backend requests. It captures the real rendered app at 390/320/1600 px.

`--narrow-map-regression` is a negative browser probe: restoring the previous 45/55 phone-map geometry makes the viewport check fail. The short-height browser check tests composer reachability when the viewport shrinks; physical iOS/Android keyboard and device performance remain device checks.

## Source and state

- `LeoPage` in `frontend/src/app/page.tsx` owns `chatDialogRef` and `isMobileChatOpen`. `openMobileChat()` calls native `showModal()`; `closeMobileChat()` closes that same dialog. A media-query listener uses nonmodal `show()` for the desktop column and closes it for the phone map.
- The existing `ChatPanel` stays mounted. Its input state and the existing `useLeoClient` messages/layers survive closing and resizing. The three prepared queries select the original retained scorer output through the existing example allowlist.
- `syncViewport()` scopes visible-height/offset variables to `workspaceRef`. Dialog CSS uses the smaller of the dynamic CSS viewport and the visible viewport; resize/scroll listeners are removed when the workspace unmounts.
- `ChatPanel` keeps its original input/submission behavior. The 48 px minimum covers the first hidden-dialog measurement; phone typography and full-width padding keep the placeholder and typed text readable.
- `ThoughtDrawer` uses a native dialog with the existing `isOpen`, `onClose` and log props. The map's existing layer/3D actions retain their handlers; the layer popover reserves space for the zoom controls.

Example mode, backend authorization, frozen query/data handling and live operator credential setup retain their existing contracts in [agent setup](AGENT-SETUP.md) and [security review](SECURITY-REVIEW.md).
