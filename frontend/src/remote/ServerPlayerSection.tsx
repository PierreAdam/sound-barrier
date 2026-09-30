import { useEffect, useState } from "react";

import { api, type ServerPlayerInfo } from "../api/native";
import { playOnDevice, remotePlaybackLabel, stopDevice, vlcLink } from "../cast/remotePlayback";
import { canPresent, present, stopPresenting } from "../cast/presentation";
import {
  type CastState,
  castScreenWithDashCast,
  castState,
  castStream,
  DEFAULT_RECEIVER,
  loadCast,
  onCastState,
  screenUrl,
  stopCasting,
} from "../cast/sender";
import { CheckIcon, CopyIcon, StopIcon } from "../components/Icons";
import { InfoTip } from "../components/InfoTip";
import { MenuSection } from "../components/PlaybackMenu";
import type { LinkTarget } from "./link";
import { controlTarget, getPlayerMode, playHere } from "./mode";
import { disableRemoteTarget, getRemoteTarget } from "./target";

/** Its name, as the backend registers it (services/server_player.py). */
const SERVER_PLAYER = "Server player";

/**
 * The ways to cast it: the Now playing screen on the Chromecast (our receiver, or DashCast
 * without one), that screen mirrored by this computer (private), the sound only (Google's
 * receiver; or, without the Cast SDK, the browser's own picker: phones, AirPlay).
 */
type CastWay = "screen" | "computer" | "audio" | "browser";

/**
 * "Playing on" menu: the user's server player. It plays on the server, as a stream that a
 * Chromecast, VLC or any internet radio app plays, and is controlled like another device.
 */
export function ServerPlayerSection({
  target,
  active,
  close,
}: {
  target: LinkTarget | null; // its entry in remote control, once listed
  active: boolean; // controlled from here now
  close(): void;
}) {
  const [player, setPlayer] = useState<ServerPlayerInfo | null | undefined>(undefined); // undefined: loading
  const [cast, setCast] = useState<CastState>(castState());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [castChoices, setCastChoices] = useState(false); // "▾": the other ways to cast

  useEffect(() => {
    let cancelled = false;
    api.getServerPlayer().then(
      (info) => !cancelled && setPlayer(info),
      () => !cancelled && setPlayer(null),
    );
    void loadCast().then(() => setCast(castState()));
    const unsubscribe = onCastState(setCast);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const control = (info: ServerPlayerInfo) => {
    if (getRemoteTarget().kind !== "off") disableRemoteTarget();
    controlTarget(info.target, SERVER_PLAYER, "server");
  };

  const start = () =>
    run(async () => {
      const info = await api.startServerPlayer();
      setPlayer(info);
      control(info);
      close();
    });

  const castWith = (info: ServerPlayerInfo, way: CastWay) =>
    run(async () => {
      setCastChoices(false);
      if (way === "browser") {
        if (await playOnDevice(info.streamUrl)) control(info);
        return;
      }
      if (way === "computer") {
        if (!(await present(screenUrl(info.streamUrl)))) return; // no device chosen
        control(info);
        setMessage("Now playing shown from this computer: keep it on, with Chrome open");
        return;
      }
      let device: string | null;
      if (way === "screen" && !info.receiverAppId) {
        device = await castScreenWithDashCast(info.streamUrl);
      } else {
        const appId = way === "screen" && info.receiverAppId ? info.receiverAppId : DEFAULT_RECEIVER;
        device = await castStream(info.streamUrl, "Sound-Barrier", SERVER_PLAYER, appId);
      }
      if (!device) return; // no device chosen
      control(info); // what the device plays is driven from here
      setMessage(`Casting to ${device}${way === "audio" ? " (sound only)" : ""}`);
    });

  // No Cast SDK here, or it finds no device (phones): the browser's own picker instead
  // (Chromecast on Android, AirPlay on Safari), which looks for devices itself.
  const sdkCast = cast !== "UNAVAILABLE" && cast !== "NO_DEVICES_AVAILABLE";
  const fallback = sdkCast ? null : remotePlaybackLabel();
  // What this browser can do, best first: the first one is "Cast…", the others under "▾".
  const ways: CastWay[] = [];
  if (sdkCast && player && (player.receiverAppId || player.dashcast)) ways.push("screen");
  if (player && canPresent()) ways.push("computer");
  if (sdkCast) ways.push("audio");
  else if (fallback) ways.push("browser");
  const WAYS: Record<CastWay, { label: string; note: string }> = {
    screen: {
      label: "Cast with Now playing",
      note: player?.receiverAppId
        ? "Cover, progress and lyrics on the TV"
        : "Cover, progress and lyrics on the TV, through DashCast (a third party's receiver: it is given the stream's address)",
    },
    computer: {
      label: "Cast from this computer",
      note: "The same screen, shown by Chrome here: private, but this computer stays on",
    },
    audio: { label: "Cast audio only", note: "Google's own receiver: works on every Chromecast" },
    browser: {
      label: fallback === "AirPlay…" ? "AirPlay (sound only)" : "Cast audio only",
      note: "The browser's own device picker: the sound only",
    },
  };
  // The button: "AirPlay…" when that is the first way (Safari), else "Cast…".
  const castLabel = ways[0] === "browser" && fallback ? fallback : "Cast…";

  const copy = (info: ServerPlayerInfo) =>
    run(async () => {
      await navigator.clipboard.writeText(info.streamUrl);
      setMessage("Stream URL copied");
    });

  const stop = () =>
    run(async () => {
      await stopCasting().catch(() => undefined);
      stopDevice();
      stopPresenting();
      await api.stopServerPlayer();
      const mode = getPlayerMode();
      if (mode.kind === "remote" && mode.targetKind === "server") playHere();
      setPlayer(null);
    });

  const track = target?.state?.current;
  return (
    <>
      <MenuSection title={SERVER_PLAYER} info="About the server player">
        <strong>The server player</strong> plays on the server itself, as a stream: cast it to a Chromecast (Chrome,
        Edge, Chrome on Android), AirPlay it (Safari), or open it in VLC, which can cast it too (the way from an
        iPhone to a Chromecast), or any app that plays internet radio. Control it from here or any of your devices,
        like another device; closing this page does not stop it.
      </MenuSection>
      {player === undefined ? null : player === null ? (
        <button className="dropdown__item" type="button" disabled={busy} onClick={() => void start()}>
          Start the server player
        </button>
      ) : (
        <>
          <button
            className={`dropdown__item player-switch-menu__item${active ? " dropdown__item--active" : ""}`}
            type="button"
            role="menuitemradio"
            aria-checked={active}
            onClick={() => {
              control(player);
              close();
            }}
          >
            <span className="player-switch-menu__check">{active && <CheckIcon />}</span>
            <span className="player-switch-menu__name">{SERVER_PLAYER}</span>
            <span className="player-switch-menu__detail">
              {track ? `${target?.state?.playing ? "▶ " : ""}${track.title}` : `${player.listeners} listening`}
            </span>
          </button>
          <div className="remote-menu__actions">
            {(ways.length > 0 || cast === "NO_DEVICES_AVAILABLE") && (
              <span className="split-button">
                <button
                  className="button button--ghost"
                  type="button"
                  disabled={busy || !ways[0]}
                  title={ways[0] ? WAYS[ways[0]].note : "No Cast device found on this network"}
                  onClick={() => {
                    if (ways[0]) void castWith(player, ways[0]);
                  }}
                >
                  {castLabel}
                </button>
                {ways.length > 1 && (
                  <button
                    className="button button--ghost split-button__more"
                    type="button"
                    aria-label="Other ways to cast"
                    aria-expanded={castChoices}
                    disabled={busy}
                    onClick={() => setCastChoices(!castChoices)}
                  >
                    ▾
                  </button>
                )}
              </span>
            )}
            {vlcLink(player.streamUrl) && (
              <a
                className="button button--ghost"
                href={vlcLink(player.streamUrl) ?? undefined}
                title="VLC plays the stream, and can cast it to a Chromecast"
              >
                Open in VLC
              </a>
            )}
            {/* Icons: the row fits on one line, next to Cast (and VLC on phones). */}
            <button
              className="button button--ghost remote-menu__icon-action"
              type="button"
              aria-label="Copy the stream's URL"
              title="Copy the stream's URL (for VLC, an internet radio app...)"
              disabled={busy}
              onClick={() => void copy(player)}
            >
              <CopyIcon />
            </button>
            <button
              className="button button--ghost remote-menu__icon-action"
              type="button"
              aria-label="Stop the server player"
              title="Stop the server player (its queue goes)"
              disabled={busy}
              onClick={() => void stop()}
            >
              <StopIcon />
            </button>
          </div>
          {castChoices && ways.length > 1 && (
            <div className="remote-menu__cast-choices" role="group" aria-label="Cast">
              {ways.map((way) => (
                <button
                  key={way}
                  className="dropdown__item"
                  type="button"
                  disabled={busy}
                  onClick={() => void castWith(player, way)}
                >
                  {WAYS[way].label}
                  <span className="remote-menu__note">{WAYS[way].note}</span>
                </button>
              ))}
            </div>
          )}
          <div className="playback-menu__option">
            <label className="dropdown__item remote-menu__option">
              <input
                type="checkbox"
                checked={player.alwaysOn}
                disabled={busy}
                onChange={(e) => {
                  const alwaysOn = e.target.checked;
                  void run(async () => setPlayer(await api.setServerPlayer(alwaysOn)));
                }}
              />
              <span>Play even when nobody listens</span>
            </label>
            <InfoTip label="About playing without listeners">
              <strong>Like a radio</strong>: it goes on even with no device connected to its stream. Otherwise it
              waits where it is until a device listens ({player.listeners} now), so nothing is missed.
            </InfoTip>
          </div>
        </>
      )}
      {message && <p className="dropdown__header remote-menu__note">{message}</p>}
    </>
  );
}
