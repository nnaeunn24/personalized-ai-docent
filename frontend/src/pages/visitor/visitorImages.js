export function exhibitionImage(exhibition) {
  return exhibition.image_url || null;
}

export function exhibitionVenue(exhibition) {
  return exhibition.venue || null;
}

export function artworkImage(artwork) {
  return artwork.image_url || null;
}
