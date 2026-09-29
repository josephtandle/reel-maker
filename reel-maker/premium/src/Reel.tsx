// SPDX-License-Identifier: MIT
import React, {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill, Img, OffthreadVideo, cancelRender, continueRender, delayRender,
  interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
} from 'remotion';
import {loadFont as loadFraunces} from '@remotion/google-fonts/Fraunces';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {palette, rgba} from './colors';

const display = loadFraunces('normal', {weights: ['600'], subsets: ['latin']});
const italic = loadFraunces('italic', {weights: ['600'], subsets: ['latin']});
const sans = loadInter('normal', {weights: ['500', '800', '900'], subsets: ['latin']});
const serif = `${display.fontFamily}, Georgia, serif`;

export type Word = {text: string; start: number; end: number};
export type Crop = {x: number; y: number; w: number; h: number; mode?: 'cover' | 'contain'};
export type ReelProps = {
  videoFile: string; videoWidth: number; videoHeight: number; durationSec: number; fps?: number;
  eyebrow: string; headline: string; words: Word[];
  cropSegments: {from: number; to: number; crop: Crop}[];
  speakers: {from: number; to: number; name: string; role?: string}[];
  brandName: string; handle: string; brandColor: string; accentColor?: string; cta: string;
  logoFile?: string; logoAspect?: number;
};

type TitleWord = {text: string; emphasis: boolean; index: number};
type TitleLayout = {lines: TitleWord[][]; size: number};

const Headline: React.FC<{text: string; tint: string}> = ({text, tint}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const [handle] = useState(() => delayRender('Measure headline fonts'));
  const [layout, setLayout] = useState<TitleLayout>({lines: [], size: 100});
  useEffect(() => {
    let alive = true;
    Promise.all([display.waitUntilDone(), italic.waitUntilDone()]).then(() => {
      const context = document.createElement('canvas').getContext('2d');
      if (!context) throw new Error('Cannot measure headline');
      let emphasized = false;
      const tokens: TitleWord[] = text.trim().split(/\s+/).filter(Boolean).map((token, index) => {
        const emphasis = !emphasized && /\*[^*]+\*/.test(token);
        if (emphasis) emphasized = true;
        return {text: token.replace(/\*/g, ''), emphasis, index};
      });
      let result: TitleLayout = {lines: [], size: 100};
      // Explicit measured line breaks guarantee the title stays above the card.
      for (let size = 100; size >= 1; size -= 1) {
        const lines: TitleWord[][] = [[]];
        let width = 0;
        let widest = 0;
        for (const token of tokens) {
          context.font = `${token.emphasis ? 'italic ' : ''}600 ${size}px ${display.fontFamily}`;
          const wordWidth = context.measureText(token.text).width;
          const space = context.measureText(' ').width;
          if (width && width + space + wordWidth > 936) {lines.push([]); width = 0;}
          width += (width ? space : 0) + wordWidth;
          widest = Math.max(widest, width);
          lines[lines.length - 1].push(token);
        }
        result = {lines, size};
        if (lines.length <= 3 && lines.length * size * 1.02 <= 248 && widest <= 936) break;
      }
      if (alive) {setLayout(result); continueRender(handle);}
    }).catch((error: Error) => cancelRender(error));
    return () => {alive = false;};
  }, [text, handle]);
  return <div style={{position: 'absolute', left: 72, right: 72, top: 185,
    fontFamily: serif, fontSize: layout.size, fontWeight: 600, lineHeight: 1.02}}>
    {layout.lines.map((line, index) => <div key={index} style={{whiteSpace: 'nowrap'}}>
      {line.map((word, i) => {
        const rise = spring({frame: Math.max(0, frame - word.index * 2), fps, config: {damping: 18}});
        return <React.Fragment key={word.index}>{i > 0 ? ' ' : ''}<span style={{
          display: 'inline-block', transform: `translateY(${(1 - rise) * 9}px)`,
          // The hook is fully legible on the cover frame; only its position animates.
          color: word.emphasis ? tint : 'white', fontStyle: word.emphasis ? 'italic' : 'normal',
          textShadow: word.emphasis ? `0 0 25px ${tint}` : undefined,
        }}>{word.text}</span></React.Fragment>;
      })}
    </div>)}
  </div>;
};

export const captionPages = (words: Word[]): Word[][] => {
  const pages: Word[][] = [];
  let page: Word[] = [];
  for (const word of words) {
    const previous = page[page.length - 1];
    if (page.length && (page.length >= 3 || [...page, word].map((w) => w.text).join(' ').length > 20
      || word.start - previous.end > 0.55 || /[.!?,;:]["'’”)\]]*$/.test(previous.text))) {
      pages.push(page); page = [];
    }
    page.push(word);
  }
  if (page.length) pages.push(page);
  return pages;
};

const VideoLayer: React.FC<{props: ReelProps; crop: Crop; zoom: number}> = ({props, crop, zoom}) => {
  const boxW = 960, boxH = 990;
  const contain = crop.mode === 'contain';
  const s0 = (contain ? Math.min : Math.max)(boxW / crop.w, boxH / crop.h);
  const s = s0 * (contain ? 1 : zoom);
  const cx = crop.x + crop.w / 2;
  const cy = crop.y + crop.h / 2;
  const py = crop.y + 0.15 * crop.h;
  const left = boxW / 2 - cx * s;
  const top = boxH / 2 - cy * s0 + py * (s0 - s);
  const edge = (-crop.y / crop.h) * boxH;
  const video = <OffthreadVideo src={staticFile(props.videoFile)} style={{position: 'absolute',
    width: props.videoWidth * s, height: props.videoHeight * s,
    maxWidth: 'none', left: contain ? -crop.x * s : left,
    top: contain ? -crop.y * s : top}} />;
  if (contain) return <div style={{position: 'absolute', overflow: 'hidden', borderRadius: 28,
    width: crop.w * s, height: crop.h * s,
    left: (boxW - crop.w * s) / 2, top: (boxH - crop.h * s) / 2}}>{video}</div>;
  return <AbsoluteFill style={crop.y < 0 ? {
    maskImage: `linear-gradient(to bottom, transparent ${edge}px, black ${edge + 40}px)`,
    WebkitMaskImage: `linear-gradient(to bottom, transparent ${edge}px, black ${edge + 40}px)`,
  } : undefined}>{video}</AbsoluteFill>;
};

export const Reel: React.FC<ReelProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const t = frame / fps;
  const colors = palette(props.brandColor, props.accentColor);
  const brand = rgba(colors.brand), tint = rgba(colors.tint), accent = rgba(colors.accent);
  const gradient = `linear-gradient(110deg, ${brand}, ${tint})`;
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 100}});
  const pulse = (Math.sin(t * 1.8) + 1) / 2;
  const segment = props.cropSegments.find((s) => t >= s.from && t < s.to);
  const crop = segment?.crop ?? {x: 0, y: 0, w: props.videoWidth, h: props.videoHeight, mode: 'contain' as const};
  const zoom = 1 + 0.03 * Math.max(0, Math.min(1, (t - (segment?.from ?? 0)) / Math.max(0.1, (segment?.to ?? props.durationSec) - (segment?.from ?? 0))));
  const speaker = props.speakers.find((s) => t >= s.from && t < s.to && s.name);
  const speakerIn = spring({frame: frame - Math.round((speaker?.from ?? 0) * fps), fps, config: {damping: 18}});
  const pages = useMemo(() => captionPages(props.words), [props.words]);
  const page = pages.find((p, i) => t >= p[0].start && t < Math.min(
    pages[i + 1]?.[0].start ?? props.durationSec, p[p.length - 1].end + 0.55));
  const pageIn = spring({frame: frame - Math.round((page?.[0].start ?? 0) * fps), fps, config: {damping: 15}});
  const ctaStart = Math.max(0, durationInFrames - Math.round(4.5 * fps));
  const ctaIn = spring({frame: frame - ctaStart, fps, config: {damping: 17}});
  const fade = durationInFrames <= 1 ? 1 : interpolate(frame, [Math.max(0, durationInFrames - 8), durationInFrames - 1], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{backgroundColor: '#0B0A10', color: 'white', fontFamily: sans.fontFamily}}>
    <AbsoluteFill style={{opacity: fade}}>
      <OffthreadVideo muted src={staticFile(props.videoFile)} style={{position: 'absolute', width: '100%', height: '100%',
        objectFit: 'cover', filter: 'blur(55px) brightness(0.27)', transform: 'scale(1.12)'}} />
      <AbsoluteFill style={{background: `radial-gradient(ellipse at 95% 7%, ${rgba(colors.brand, 0.2 + pulse * 0.1)}, transparent 57%), radial-gradient(ellipse at 5% 90%, ${rgba(colors.accent, 0.19)}, transparent 52%), linear-gradient(to bottom, rgba(11,10,16,0.12), rgba(11,10,16,0.85))`}} />
      <div style={{position: 'absolute', left: 72, top: 120, display: 'flex', alignItems: 'center', gap: 18,
        transform: `translateX(${(1 - entrance) * -22}px)`, fontSize: 26, fontWeight: 500,
        textTransform: 'uppercase', letterSpacing: 6}}>
        <span style={{width: 11, height: 11, borderRadius: '50%', background: accent, boxShadow: `0 0 24px ${accent}`}} />
        {props.eyebrow}
      </div>
      <Headline text={props.headline} tint={tint} />
      <div style={{position: 'absolute', left: 60, top: 450, width: 960, height: 990,
        borderRadius: 44, overflow: 'hidden', outline: `3px solid ${rgba(colors.tint, 0.8)}`,
        boxShadow: `0 0 ${36 + pulse * 14}px ${rgba(colors.brand, 0.32)}`,
        transform: `scale(${0.96 + entrance * 0.04})`}}>
        <OffthreadVideo muted src={staticFile(props.videoFile)} style={{position: 'absolute', width: '100%', height: '100%',
          objectFit: 'cover', filter: 'blur(28px) brightness(0.5)', transform: 'scale(1.1)'}} />
        <VideoLayer props={props} crop={crop} zoom={zoom} />
        {speaker && <div style={{position: 'absolute', bottom: 0, left: 0, right: 0, padding: '100px 40px 38px',
          background: 'linear-gradient(transparent, rgba(11,10,16,.88))'}}>
          <div style={{borderLeft: `6px solid ${accent}`, paddingLeft: 22, opacity: speakerIn,
            transform: `translateY(${(1 - speakerIn) * 22}px)`}}>
            <div style={{fontFamily: serif, fontSize: 58, lineHeight: 1.1}}>{speaker.name}</div>
            <div style={{fontSize: 27, color: tint, marginTop: 8}}>{speaker.role}</div>
          </div>
        </div>}
        {props.logoFile && <Img src={staticFile(props.logoFile)} style={{position: 'absolute', right: 40, top: 40,
          width: 72, height: 72 / Math.max(0.1, props.logoAspect ?? 1), objectFit: 'contain', opacity: 0.92,
          filter: 'drop-shadow(0 3px 8px rgba(0,0,0,.6))'}} />}
      </div>
      <div style={{position: 'absolute', top: 1460, left: 70, right: 70, height: 250, display: 'flex',
        justifyContent: 'center', alignItems: 'center', gap: 14, flexWrap: 'wrap', alignContent: 'center',
        transform: `scale(${0.9 + pageIn * 0.1})`, opacity: page ? 1 : 0,
        fontSize: 56, fontWeight: 900, lineHeight: 1.3}}>
        {page?.map((word, i) => {
          const active = t >= word.start && t < word.end;
          return <span key={i} style={{padding: '8px 14px', borderRadius: 19, maxWidth: '100%', overflowWrap: 'anywhere',
            fontSize: word.text.length > 20 ? Math.max(18, 56 * 20 / word.text.length) : undefined,
            color: active ? '#0B0A10' : t >= word.end ? 'white' : 'rgba(255,255,255,.55)',
            background: active ? gradient : undefined,
            transform: active ? 'scale(1.045) rotate(-1.5deg)' : undefined}}>{word.text}</span>;
        })}
      </div>
      <div style={{position: 'absolute', top: 1770, left: 60, right: 60, textAlign: 'center'}}>
        {frame >= ctaStart && props.cta ? <div style={{display: 'inline-block', maxWidth: 880,
          background: `linear-gradient(110deg, ${accent}, ${tint})`, color: '#0B0A10',
          borderRadius: 60, padding: '22px 42px', fontSize: props.cta.length > 45 ? 28 : 36,
          fontWeight: 800, transform: `translateY(${(1 - ctaIn) * 60}px) scale(${0.9 + ctaIn * 0.1})`, opacity: ctaIn}}>{props.cta}</div>
          : <div style={{opacity: 0.55, fontSize: 28}}><span style={{fontFamily: serif, fontStyle: 'italic'}}>{props.brandName}</span>{props.brandName && props.handle ? ' · ' : ''}{props.handle}</div>}
      </div>
      <div style={{position: 'absolute', bottom: 0, left: 0, height: 10,
        width: `${100 * (frame + 1) / durationInFrames}%`,
        background: `linear-gradient(90deg, ${brand}, ${tint}, ${accent})`, boxShadow: `0 0 22px ${brand}`}} />
    </AbsoluteFill>
  </AbsoluteFill>;
};
