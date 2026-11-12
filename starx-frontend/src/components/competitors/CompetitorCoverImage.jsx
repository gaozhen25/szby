import { useEffect, useState } from "react";

import { browserCompatibleImageUrl } from "../../utils/publicImageUrl.js";

export default function CompetitorCoverImage({ url }) {
  const [failed, setFailed] = useState(false);
  const imageUrl = browserCompatibleImageUrl(url);

  useEffect(() => setFailed(false), [imageUrl]);

  return imageUrl && !failed
    ? <img src={imageUrl} alt="" onError={() => setFailed(true)} />
    : <span aria-hidden="true">▶</span>;
}
