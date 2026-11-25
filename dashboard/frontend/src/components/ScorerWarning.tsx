import HelpHint from './HelpHint'

export default function ScorerWarning({ reasons, details, detailsOnly = false }: { reasons: string[]; details: string[]; detailsOnly?: boolean }) {
  if (detailsOnly) return <HelpHint label="Details" text={details.join('\n\n')} />
  return <HelpHint label="Warning" text={reasons.join('\n')} details={details} />
}
