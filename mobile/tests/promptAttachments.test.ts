import { getPromptAttachments, PromptAttachment } from '../utils/promptAttachments';

const firstPromptImage: PromptAttachment = {
  id: 'first-image',
  uri: 'file:///first-image.png',
  name: 'first-image.png',
  type: 'image',
};

const staleComposerAttachments = [firstPromptImage];
const queuedSecondPromptAttachments: PromptAttachment[] = [];

const secondPromptAttachments = getPromptAttachments(
  queuedSecondPromptAttachments,
  staleComposerAttachments,
);

if (secondPromptAttachments.length !== 0) {
  throw new Error('A queued prompt inherited attachments from the previous prompt.');
}

const queuedOwnImageSnapshot = [firstPromptImage];
const queuedOwnImage = getPromptAttachments(queuedOwnImageSnapshot, []);
if (queuedOwnImage.length !== 1 || queuedOwnImage[0] !== firstPromptImage) {
  throw new Error('A queued prompt did not retain its own attachment.');
}

if (queuedOwnImage === queuedOwnImageSnapshot) {
  throw new Error('Prompt attachments must be copied into an isolated snapshot.');
}
