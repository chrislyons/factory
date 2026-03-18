import { bootstrapApp } from "../app/bootstrap";
import { AgentDetailPage } from "../pages/AgentDetailPage";
import type { AgentId } from "../lib/types";

const agentId = (document.body.dataset.agentId ?? "boot") as AgentId;

bootstrapApp(<AgentDetailPage agentId={agentId} />);
