import { useCallback, useState } from "react";
import Lightbox from "yet-another-react-lightbox";
import Counter from "yet-another-react-lightbox/plugins/counter";
import Download from "yet-another-react-lightbox/plugins/download";
import Fullscreen from "yet-another-react-lightbox/plugins/fullscreen";
import Thumbnails from "yet-another-react-lightbox/plugins/thumbnails";
import Video from "yet-another-react-lightbox/plugins/video";
import Zoom from "yet-another-react-lightbox/plugins/zoom";

import { downloadMedia } from "../utils/mediaLightbox";

import "yet-another-react-lightbox/styles.css";
import "yet-another-react-lightbox/plugins/counter.css";
import "yet-another-react-lightbox/plugins/thumbnails.css";
import "../styles/media-lightbox.css";

const plugins = [Zoom, Download, Video, Counter, Fullscreen, Thumbnails];

export function useMediaLightbox() {
  const [state, setState] = useState({ open: false, index: 0, slides: [] });

  const openMedia = useCallback((slides = [], index = 0) => {
    const nextSlides = (Array.isArray(slides) ? slides : []).filter(Boolean);
    if (!nextSlides.length) return;
    setState({
      open: true,
      index: Math.min(Math.max(Number(index) || 0, 0), nextSlides.length - 1),
      slides: nextSlides,
    });
  }, []);

  const closeMedia = useCallback(() => {
    setState((current) => ({ ...current, open: false }));
  }, []);

  const setMediaIndex = useCallback((index) => {
    setState((current) => ({ ...current, index }));
  }, []);

  return {
    open: state.open,
    index: state.index,
    slides: state.slides,
    openMedia,
    closeMedia,
    setMediaIndex,
  };
}

export default function MediaLightbox({
  open = false,
  index = 0,
  slides = [],
  onClose,
  onIndexChange,
}) {
  const safeSlides = Array.isArray(slides) ? slides.filter(Boolean) : [];
  const isOpen = Boolean(open && safeSlides.length);

  return (
    <Lightbox
      className="starx-media-lightbox"
      open={isOpen}
      close={onClose}
      index={Math.min(Math.max(Number(index) || 0, 0), Math.max(safeSlides.length - 1, 0))}
      slides={safeSlides}
      plugins={plugins}
      animation={{ fade: 220 }}
      carousel={{ finite: safeSlides.length <= 1, preload: 2 }}
      controller={{ closeOnBackdropClick: true, closeOnPullDown: true }}
      zoom={{ maxZoomPixelRatio: 4, scrollToZoom: true }}
      thumbnails={{ position: "bottom", border: 0, gap: 8, padding: 12, height: 64 }}
      video={{ controls: true, playsInline: true, autoPlay: true }}
      on={{
        view: ({ index: nextIndex }) => onIndexChange?.(nextIndex),
      }}
      download={{
        download: async ({ slide }) => {
          const url = slide?.src || slide?.sources?.[0]?.src || "";
          const filename = slide?.downloadFilename
            || (slide?.type === "video" ? "starx-video.mp4" : "starx-image.png");
          await downloadMedia(url, filename);
        },
      }}
      render={{
        buttonPrev: safeSlides.length <= 1 ? () => null : undefined,
        buttonNext: safeSlides.length <= 1 ? () => null : undefined,
        slideHeader: ({ slide }) => slide?.title ? (
          <div className="starx-lightbox-title">{slide.title}</div>
        ) : null,
      }}
      styles={{
        container: { backgroundColor: "rgba(4, 12, 26, 0.88)" },
      }}
    />
  );
}
