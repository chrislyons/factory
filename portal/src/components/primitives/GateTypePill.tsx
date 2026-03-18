import type { ApprovalGateType } from "../../lib/types";
import { approvalGateColor, approvalGateLabel } from "../../lib/utils";

export function GateTypePill({ gateType }: { gateType: ApprovalGateType }) {
  return (
    <span className="gate-pill" style={{ ["--gate-color" as string]: approvalGateColor(gateType) }}>
      {approvalGateLabel(gateType)}
    </span>
  );
}
