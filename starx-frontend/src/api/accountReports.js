import { apiClient } from "./client.js";

const createSectionWorkflow = (accountId, sectionPath, referenceComments = false) => (
  apiClient.post(`/accounts/${accountId}/report/${sectionPath}/workflows`, { referenceComments })
);

/** 账号报告 API。四个可见板块拥有独立端点，与后端 workflow 类型一一对应。 */
export const accountReportApi = {
  getReport: (accountId) => apiClient.get(`/accounts/${accountId}/report`),
  resolveReportSimilarAccount: (accountId, profileUrl) =>
    apiClient.post(`/accounts/${accountId}/report/similar-accounts/resolve`, { profileUrl }),
  addReportSimilarAccount: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/report/similar-accounts`, payload),
  deleteReportSimilarAccount: (accountId, configurationKey) =>
    apiClient.delete(`/accounts/${accountId}/report/similar-accounts/${encodeURIComponent(configurationKey)}`),
  updateReportSimilarAccount: (accountId, configurationKey, payload) =>
    apiClient.patch(
      `/accounts/${accountId}/report/similar-accounts/${encodeURIComponent(configurationKey)}`,
      payload,
    ),
  createReportWorkflow: (accountId, referenceComments = false) =>
    apiClient.post(`/accounts/${accountId}/report/workflows`, { referenceComments }),
  createSimilarAccountsReportWorkflow: (accountId, referenceComments = false) =>
    createSectionWorkflow(accountId, "similar-accounts", referenceComments),
  createComplianceRulesReportWorkflow: (accountId, referenceComments = false) =>
    createSectionWorkflow(accountId, "compliance-rules", referenceComments),
  createTargetUserProfileReportWorkflow: (accountId, referenceComments = false) =>
    createSectionWorkflow(accountId, "target-user-profile", referenceComments),
  createHotContentsReportWorkflow: (accountId, referenceComments = false) =>
    createSectionWorkflow(accountId, "hot-contents", referenceComments),
  getLatestReportWorkflow: (accountId) =>
    apiClient.get(`/accounts/${accountId}/report/workflows/latest`),
  getActiveReportWorkflows: (accountId) =>
    apiClient.get(`/accounts/${accountId}/report/workflows/active`),
  getReportWorkflow: (accountId, workflowId) =>
    apiClient.get(`/accounts/${accountId}/report/workflows/${workflowId}`),
  updateReportSection: (accountId, sectionKey, content) =>
    apiClient.put(`/accounts/${accountId}/report/sections/${sectionKey}`, { content }),
};
