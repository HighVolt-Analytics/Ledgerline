import { useRef, useState } from "react";

import { CheckCircle2, FileUp, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { DocumentTypeDefinition, DocumentTypeSampleAnalysis } from "@/lib/v5DocumentTypes";

import type { DocumentTypeTemplateId } from "@/lib/documentTypeTemplates";

import {

  analyzeDocumentTypeSamples,
  analyzeSamplesErrorMessage,
  buildSampleAnalysisRecord,
  formatProposalSummary,
  formatSampleAnalysisWhen,
  mergeSampleProposalIntoDraft,

  type DocumentTypeSampleProposal,

} from "@/lib/documentTypeSampleAnalysis";



type DocumentTypeSamplesSectionProps = {

  draft: DocumentTypeDefinition;

  templateId: DocumentTypeTemplateId;

  sampleAnalysis?: DocumentTypeSampleAnalysis;

  onRecordAnalysis: (record: DocumentTypeSampleAnalysis) => void;

  onApply: (
    next: DocumentTypeDefinition,
    proposal: DocumentTypeSampleProposal,
    filenames: string[]
  ) => void;

  disabled?: boolean;

};



const ACCEPT = ".pdf,.jpg,.jpeg,.png,.docx";
const MAX_FILES = 10;
const MAX_FILE_BYTES = 25 * 1024 * 1024;

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function DocumentTypeSamplesSection({

  draft,

  templateId,

  sampleAnalysis,

  onRecordAnalysis,

  onApply,

  disabled,

}: DocumentTypeSamplesSectionProps) {

  const inputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<File[]>([]);

  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [proposal, setProposal] = useState<DocumentTypeSampleProposal | null>(null);



  const addFiles = (incoming: FileList | null) => {

    if (!incoming?.length) return;

    setError(null);

    setProposal(null);

    const rejected: string[] = [];

    setFiles((prev) => {

      const merged = [...prev];

      const seen = new Set(merged.map(fileKey));

      for (const file of Array.from(incoming)) {

        if (merged.length >= MAX_FILES) break;

        if (file.size > MAX_FILE_BYTES) {

          rejected.push(`${file.name} (too large)`);

          continue;

        }

        const key = fileKey(file);

        if (seen.has(key)) continue;

        seen.add(key);

        merged.push(file);

      }

      return merged;

    });

    if (rejected.length) {

      setError(`Skipped: ${rejected.join(", ")}. Max ${MAX_FILE_BYTES / (1024 * 1024)} MB per file.`);

    }

  };



  const analyze = async () => {

    if (!files.length) {

      setError("Add at least one sample file.");

      return;

    }

    setBusy(true);
    setStatus(
      files.length === 1
        ? "Analyzing sample with layout OCR…"
        : `Analyzing ${files.length} samples with layout OCR…`
    );
    setError(null);

    try {

      const result = await analyzeDocumentTypeSamples(files, {

        purchaseBundleRole: draft.purchaseBundleRole,

        draft,

      });

      if (!result?.samples?.length && !result?.recognition_signals?.length) {
        setError("Analysis finished but no fields or signals were detected. Try a clearer PDF.");
        setProposal(null);
        return;
      }

      setProposal(result);
      onRecordAnalysis(buildSampleAnalysisRecord(files.map((file) => file.name), result));

    } catch (err) {

      setError(analyzeSamplesErrorMessage(err));

    } finally {

      setBusy(false);
      setStatus(null);

    }

  };



  const apply = () => {

    if (!proposal) return;

    const filenames = files.map((file) => file.name);

    onApply(mergeSampleProposalIntoDraft(draft, proposal, templateId), proposal, filenames);

  };



  const summaryRows = proposal ? formatProposalSummary(proposal) : [];



  return (

    <div className="space-y-4" data-testid="document-type-samples">

      <div>

        <p className="text-sm text-foreground font-medium">Sample files</p>

        <p className="mt-1 text-xs text-muted-foreground">
          Upload examples to detect recognition signals, extraction fields, playbook, and routing.
          Samples are parsed with Azure layout OCR when configured.
          Apply is blocked until every sample routes cleanly to this document type.
        </p>

      </div>



      {sampleAnalysis ? (
        <div
          className="rounded-md border border-border/80 bg-muted/25 p-3 text-xs space-y-1.5"
          data-testid="document-type-samples-history"
        >
          <p className="font-medium text-foreground inline-flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5 text-primary shrink-0" />
            Sample analysis on record
          </p>
          <p className="text-muted-foreground">
            {sampleAnalysis.fileCount} file{sampleAnalysis.fileCount === 1 ? "" : "s"} analyzed{" "}
            {formatSampleAnalysisWhen(sampleAnalysis.analyzedAt)}
            {sampleAnalysis.appliedAt
              ? ` · suggestions applied ${formatSampleAnalysisWhen(sampleAnalysis.appliedAt)}`
              : " · suggestions not applied yet"}
          </p>
          {sampleAnalysis.filenames.length ? (
            <p className="text-muted-foreground break-words">
              {sampleAnalysis.filenames.join(", ")}
            </p>
          ) : null}
          {sampleAnalysis.recognitionSignals.length ? (
            <p className="text-muted-foreground">
              Signals: {sampleAnalysis.recognitionSignals.join(", ")}
            </p>
          ) : null}
          <p className="text-[11px] text-muted-foreground/90">
            Save this document type to keep the analysis record.
          </p>
        </div>
      ) : null}



      <input

        ref={inputRef}

        type="file"

        accept={ACCEPT}

        multiple

        className="sr-only"

        disabled={disabled || busy}

        onChange={(e) => {

          addFiles(e.target.files);

          e.target.value = "";

        }}

      />



      <div className="flex flex-wrap items-center gap-2">

        <Button

          type="button"

          variant="outline"

          size="sm"

          disabled={disabled || busy || files.length >= MAX_FILES}

          onClick={() => inputRef.current?.click()}

        >

          <FileUp className="mr-1.5 h-3.5 w-3.5" />

          Add files

        </Button>

        <Button

          type="button"

          size="sm"

          disabled={disabled || busy || !files.length}

          onClick={() => void analyze()}

        >

          {busy ? (

            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />

          ) : (

            <Sparkles className="mr-1.5 h-3.5 w-3.5" />

          )}

          Analyze samples

        </Button>

        {files.length ? (

          <Button

            type="button"

            variant="ghost"

            size="sm"

            disabled={busy}

            onClick={() => {

              setFiles([]);

              setProposal(null);

              setError(null);

            }}

          >

            Clear

          </Button>

        ) : null}

      </div>



      {files.length ? (

        <ul className="space-y-1 rounded-md border border-border bg-muted/20 p-3 text-xs">

          {files.map((file) => (

            <li key={fileKey(file)} className="truncate text-foreground">

              {file.name}

            </li>

          ))}

        </ul>

      ) : null}



      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      {status ? <p className="text-xs text-muted-foreground">{status}</p> : null}



      {proposal ? (

        <div className="space-y-3 rounded-md border border-primary/25 bg-primary/5 p-3">

          <p className="text-sm font-medium text-foreground">Suggested settings</p>

          {proposal.reasoning ? (
            <p className="text-xs text-foreground">
              Suggested because: {proposal.reasoning}
            </p>
          ) : null}

          {proposal.catalogue_matches?.length ? (
            <div className="space-y-1">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Similar catalogue types
              </p>
              {proposal.catalogue_matches.map((match) => (
                <p key={match.code} className="text-xs text-muted-foreground">
                  {match.code} — {match.title} ({Math.round(match.similarity * 100)}%)
                </p>
              ))}
            </div>
          ) : null}

          {proposal.apply_block_reason ? (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {proposal.apply_block_reason}
            </p>
          ) : null}

          {proposal.recognition_signal_details?.length ? (
            <div className="space-y-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Detected signals (detail)
              </p>
              <div className="overflow-x-auto rounded-md border border-border/70">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1.5 font-medium">Signal</th>
                      <th className="px-2 py-1.5 font-medium">Channel</th>
                      <th className="px-2 py-1.5 font-medium">Strength</th>
                      <th className="px-2 py-1.5 font-medium">What it means</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposal.recognition_signal_details.map((row) => (
                      <tr key={row.signal_id} className="border-t border-border/50">
                        <td className="px-2 py-1.5 font-medium text-foreground">{row.label}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{row.channel}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{row.strength}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">
                          {row.hint}
                          {row.example ? (
                            <span className="block text-[10px] opacity-80">e.g. {row.example}</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {proposal.suggested_signals?.length ? (
            <div className="space-y-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
                Suggested signals to add (stronger identification)
              </p>
              <ul className="space-y-1.5 text-xs">
                {proposal.suggested_signals.map((row) => (
                  <li
                    key={row.signal_id}
                    className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5"
                  >
                    <span className="font-medium text-foreground">{row.label}</span>
                    <span className="text-muted-foreground"> — {row.hint}</span>
                    {row.example ? (
                      <span className="block text-[10px] text-muted-foreground">e.g. {row.example}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p className="text-[10px] text-muted-foreground">
                After Apply, open Recognition and tick these signals, or rename files / use clearer scans.
              </p>
            </div>
          ) : null}

          {proposal.notes.map((note) => (

            <p key={note} className="text-xs text-muted-foreground">

              {note}

            </p>

          ))}



          {proposal.samples.some((sample) => sample.routed_code) || proposal.samples.length > 1 ? (

            <div className="space-y-2">

              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">

                Per file

              </p>

              {proposal.samples.map((sample) => (

                <div

                  key={sample.filename}

                  className="rounded-md border border-border/70 bg-background/70 px-2.5 py-2 text-xs"

                >

                  <p className="font-medium text-foreground">{sample.filename}</p>

                  <p className="mt-1 text-muted-foreground">

                    Signals: {sample.recognition_signals.join(", ") || "none"}

                  </p>

                  <p className="text-muted-foreground">

                    Fields: {sample.extraction_fields.join(", ") || "none"}

                  </p>

                  {sample.routed_code ? (

                    <div className="mt-2 space-y-1 rounded border border-border/60 bg-muted/30 px-2 py-1.5">

                      <p className="font-medium text-foreground">

                        Catalogue route: {sample.routed_code}

                        {sample.routed_confidence != null

                          ? ` (${Math.round(sample.routed_confidence * 100)}%)`

                          : ""}

                        {sample.matches_expected === true ? " · matches this type" : null}

                        {sample.matches_expected === false ? " · mismatch" : null}

                        {sample.route_needs_review ? " · needs review" : null}

                      </p>

                      {sample.route_conflicts?.length ? (

                        <p className="text-amber-700 dark:text-amber-400">

                          Conflicts: {sample.route_conflicts.join("; ")}

                        </p>

                      ) : null}

                      {sample.route_alternatives?.length ? (

                        <p className="text-muted-foreground">

                          Alternatives:{" "}

                          {sample.route_alternatives

                            .slice(0, 3)

                            .map((alt) => `${alt.code} (${Math.round(alt.confidence * 100)}%)`)

                            .join(", ")}

                        </p>

                      ) : null}

                    </div>

                  ) : null}

                </div>

              ))}

            </div>

          ) : null}



          <dl className="grid gap-2 text-xs sm:grid-cols-2">

            {summaryRows.map((row) => (

              <div key={row.label} className={row.label === "Summary" ? "sm:col-span-2" : undefined}>

                <dt className="text-muted-foreground">{row.label}</dt>

                <dd className="mt-0.5 font-medium text-foreground break-words">{row.value}</dd>

              </div>

            ))}

          </dl>



          {proposal.apply_block_reason ? (
            <p className="text-xs text-destructive">{proposal.apply_block_reason}</p>
          ) : null}



          <Button
            type="button"
            size="sm"
            onClick={apply}
            disabled={disabled || proposal.apply_ready === false}
          >
            Apply suggested settings
          </Button>

        </div>

      ) : null}

    </div>

  );

}


