import { fileName, proxy } from "./media.js?v=1";

export function slidesOf(item) {
  if (item && item.source) return slidesFromAsset(item);
  return slidesFromExtract(item || {});
}

function slidesFromAsset(item) {
  const file = item.href || proxy(item.remote_url);
  const poster = proxy(item.poster);
  const video = item.type === "video";
  const src = video ? file : (file || poster);
  if (!src && !poster) return [];
  return [{
    type: video && src ? "video" : "image",
    src: src || poster,
    poster: video ? poster : "",
    download: file || "",
    name: item.name || "file",
    label: video ? "视频" : "图片",
  }];
}

function slidesFromExtract(item) {
  const medias = item.medias || [];
  if (!medias.length && item.cover) {
    return [{ type: "image", src: proxy(item.cover), download: "", name: "cover.jpg", label: "封面" }];
  }
  return medias.map((media, index) => {
    const name = fileName(item, media, index);
    if (media.type === "video") {
      return {
        type: "video",
        src: proxy(media.url),
        poster: proxy(item.cover),
        download: proxy(media.url, name),
        name,
        label: "视频",
      };
    }
    const many = medias.filter((entry) => entry.type === "image").length > 1;
    return {
      type: "image",
      src: proxy(media.cover || media.url),
      download: proxy(media.url, name),
      name,
      label: many ? "图片 " + (index + 1) : "图片",
    };
  });
}
