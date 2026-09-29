// SPDX-License-Identifier: MIT
import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Reel, type ReelProps} from './Reel';

const defaults: ReelProps = {
  videoFile: 'reel-1.mp4', videoWidth: 1920, videoHeight: 1080,
  durationSec: 12, fps: 30, eyebrow: '@yourhandle',
  headline: 'Build it *once*, sell it forever', words: [], cropSegments: [], speakers: [],
  brandName: 'Your Name', handle: '@yourhandle', brandColor: '#2E86DE',
  cta: 'Follow for more',
};

registerRoot(() => <Composition
  id="reel" component={Reel} width={1080} height={1920} fps={30}
  durationInFrames={360} defaultProps={defaults}
  calculateMetadata={({props}) => {
    const fps = props.fps ?? 30;
    if (!Number.isFinite(fps) || fps <= 0 || !Number.isFinite(props.durationSec) || props.durationSec <= 0) {
      throw new Error('durationSec and fps must be positive finite numbers');
    }
    return {fps, durationInFrames: Math.max(1, Math.round(props.durationSec * fps))};
  }}
/>);
