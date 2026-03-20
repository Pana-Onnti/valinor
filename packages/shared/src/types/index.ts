// Valinor Shared Types

// Common types
export interface BaseEntity {
  id: string;
  createdAt: Date;
  updatedAt: Date;
}

// User & Authentication
export interface User extends BaseEntity {
  email: string;
  name: string;
  tier: UserTier;
  isActive: boolean;
  lastLoginAt?: Date;
}

export type UserTier = 'free' | 'pro' | 'enterprise';

// Client Management
export interface Client extends BaseEntity {
  name: string;
  userId: string;
  description?: string;
  connectionString: string;
  isActive: boolean;
  tier: UserTier;
  analysisCount: number;
  lastAnalysisAt?: Date;
}

// Analysis Jobs
export interface AnalysisJob extends BaseEntity {
  clientId: string;
  status: AnalysisStatus;
  type: AnalysisType;
  config: AnalysisConfig;
  results?: AnalysisResults;
  cost: number;
  startedAt?: Date;
  completedAt?: Date;
  failedAt?: Date;
  errorMessage?: string;
}

export type AnalysisStatus = 
  | 'pending' 
  | 'queued' 
  | 'processing' 
  | 'completed' 
  | 'failed' 
  | 'cancelled';

export type AnalysisType = 
  | 'full' 
  | 'schema' 
  | 'data' 
  | 'security' 
  | 'performance';

export interface AnalysisConfig {
  includeSchema: boolean;
  includeData: boolean;
  includeSecurity: boolean;
  includePerformance: boolean;
  sampleSize: number;
  timeout: number;
}

// Analysis Results
export interface AnalysisResults {
  entityMap: EntityMap;
  findings: Finding[];
  reports: Report[];
  metrics: AnalysisMetrics;
}

export interface EntityMap {
  tables: TableEntity[];
  relationships: Relationship[];
  indexes: IndexEntity[];
  constraints: ConstraintEntity[];
}

export interface TableEntity {
  name: string;
  schema: string;
  columns: ColumnEntity[];
  rowCount: number;
  sizeBytes: number;
  lastModified?: Date;
}

export interface ColumnEntity {
  name: string;
  dataType: string;
  isNullable: boolean;
  isPrimaryKey: boolean;
  isForeignKey: boolean;
  isUnique: boolean;
  defaultValue?: string;
}

export interface Relationship {
  fromTable: string;
  fromColumn: string;
  toTable: string;
  toColumn: string;
  type: 'one-to-one' | 'one-to-many' | 'many-to-many';
}

export interface IndexEntity {
  name: string;
  table: string;
  columns: string[];
  isUnique: boolean;
  type: string;
}

export interface ConstraintEntity {
  name: string;
  table: string;
  type: 'PRIMARY' | 'FOREIGN' | 'UNIQUE' | 'CHECK';
  definition: string;
}

// Findings & Reports
export interface Finding {
  id: string;
  type: FindingType;
  severity: FindingSeverity;
  title: string;
  description: string;
  table?: string;
  column?: string;
  suggestion?: string;
  impact: 'low' | 'medium' | 'high' | 'critical';
}

export type FindingType = 
  | 'schema' 
  | 'data_quality' 
  | 'security' 
  | 'performance' 
  | 'business_logic';

export type FindingSeverity = 'info' | 'warning' | 'error' | 'critical';

export interface Report {
  id: string;
  type: ReportType;
  title: string;
  content: string;
  format: 'markdown' | 'html' | 'pdf';
  url?: string;
  generatedAt: Date;
}

export type ReportType = 
  | 'executive' 
  | 'technical' 
  | 'security' 
  | 'data_quality' 
  | 'performance';

export interface AnalysisMetrics {
  duration: number;
  tablesAnalyzed: number;
  findingsCount: number;
  reportsGenerated: number;
  costUsd: number;
}

// Database Connection
export interface DatabaseConnection {
  type: DatabaseType;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl?: boolean;
  tunnel?: SSHTunnel;
}

export type DatabaseType = 'mysql' | 'postgresql' | 'mssql' | 'oracle';

export interface SSHTunnel {
  host: string;
  port: number;
  username: string;
  password?: string;
  privateKey?: string;
  localPort: number;
}

// API Responses
export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: any;
  };
  meta?: {
    pagination?: {
      page: number;
      limit: number;
      total: number;
      pages: number;
    };
    filters?: Record<string, any>;
  };
}

export interface PaginationParams {
  page?: number;
  limit?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

// Agent Types
export interface AgentContext {
  jobId: string;
  clientId: string;
  config: AnalysisConfig;
  connection: DatabaseConnection;
  memory: Record<string, any>;
}

export interface AgentResult<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  cost: number;
  duration: number;
}

// Webhook Events
export interface WebhookEvent {
  id: string;
  type: WebhookEventType;
  data: any;
  timestamp: Date;
  retryCount: number;
}

export type WebhookEventType = 
  | 'analysis.started' 
  | 'analysis.completed' 
  | 'analysis.failed' 
  | 'user.created' 
  | 'payment.succeeded' 
  | 'payment.failed';