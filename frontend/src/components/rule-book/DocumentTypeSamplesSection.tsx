import { useRef, useState } from "react";

import { FileUp, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

import type { DocumentTypeTemplateId } from "@/lib/documentTypeTemplates";

import {

  analyzeDocumentTypeSamples,

  formatProposalSummary,

  mergeSampleProposalIntoDraft,

  type DocumentTypeSampleProposal,

} from "@/lib/documentTypeSampleAnalysis";



type DocumentTypeSamplesSectionProps = {

  draft: DocumentTypeDefinition;

  templateId: DocumentTypeTemplateId;

  onApply: (next: DocumentTypeDefinition, proposal: DocumentTypeSampleProposal) => void;

  disabled?: boolean;

};



const ACCEPT = ".pdf,.jpg,.jpeg,.png,.docx";



export function DocumentTypeSamplesSection({

  draft,

  templateId,

  onApply,

  disabled,

}: DocumentTypeSamplesSectionProps) {

  const inputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<File[]>([]);

  const [busy, setBusy] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const [proposal, setProposal] = useState<DocumentTypeSampleProposal | null>(null);



  const addFiles = (incoming: FileList | null) => {

    if (!incoming?.length) return;

    setError(null);

    setProposal(null);

    setFiles((prev) => {

      const merged = [...prev];

      for (const file of Array.from(incoming)) {

        if (merged.length >= 10) break;

        merged.push(file);

      }

      return merged;

    });

  };



  const analyze = async () => {

    if (!files.length) {

      setError("Add at least one sample file.");

      return;

    }

    setBusy(true);

    setError(null);

    try {

      const result = await analyzeDocumentTypeSamples(files, {

        purchaseBundleRole: draft.purchaseBundleRole,

        draft,

      });

      setProposal(result);

    } catch (err) {

      setError(err instanceof Error ? err.message : "Analysis failed");

    } finally {

      setBusy(false);

    }

  };



  const apply = () => {

    if (!proposal) return;

    onApply(mergeSampleProposalIntoDraft(draft, proposal, templateId), proposal);

  };



  const summaryRows = proposal ? formatProposalSummary(proposal) : [];



  return (

    <div className="space-y-4" data-testid="document-type-samples">

      <div>

        <p className="text-sm text-foreground font-medium">Sample files</p>

        <p className="mt-1 text-xs text-muted-foreground">

          Upload one or more real examples of this document type. We parse every file and suggest

          recognition, fields, validation, match, approval, and bundle settings.

        </p>

      </div>



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

          disabled={disabled || busy || files.length >= 10}

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

            <li key={`${file.name}-${file.size}`} className="truncate text-foreground">

              {file.name}

            </li>

          ))}

        </ul>

      ) : null}



      {error ? <p className="text-xs text-destructive">{error}</p> : null}



      {proposal ? (

        <div className="space-y-3 rounded-md border border-primary/25 bg-primary/5 p-3">

          <p className="text-sm font-medium text-foreground">Suggested settings</p>

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



          <Button type="button" size="sm" onClick={apply} disabled={disabled}>

            Apply all suggestions to this document type

          </Button>

        </div>

      ) : null}

    </div>

  );

}


