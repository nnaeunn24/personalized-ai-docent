import daisies from './matisse-daisies.png';
import interior from './matisse-interior-at-nice.png';
import geranium from './matisse-still-life-with-geranium.png';

const sampleExhibition = 'Matisse’s Jazz: Rhythms in Color';
const sampleArtworks = {
  Daisies: daisies,
  'Interior at Nice': interior,
  'Still Life with Geranium': geranium,
};
const matisseNames = new Set(['마티스', '앙리 마티스', 'Henri Matisse']);

export function exhibitionImage(exhibition) {
  return exhibition.image_url || (exhibition.name === sampleExhibition ? daisies : null);
}

export function exhibitionVenue(exhibition) {
  return exhibition.name === sampleExhibition ? '시카고 미술관' : null;
}

export function artworkImage(artwork) {
  return artwork.image_url || (matisseNames.has(artwork.artist) && Object.hasOwn(sampleArtworks, artwork.name)
    ? sampleArtworks[artwork.name] : null);
}
