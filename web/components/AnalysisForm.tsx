'use client'

import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import axios from 'axios'
import toast from 'react-hot-toast'
import { Database, Key, Server, ChevronDown, ChevronUp, Play } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const formSchema = z.object({
  dbType: z.enum(['postgresql', 'mysql', 'sqlserver', 'oracle']),
  dbHost: z.string().min(1, 'Host required'),
  dbPort: z.coerce.number().int().positive(),
  dbName: z.string().min(1, 'Database name required'),
  dbUser: z.string().min(1, 'Username required'),
  dbPassword: z.string().min(1, 'Password required'),
  useSSH: z.boolean().default(false),
  sshHost: z.string().optional(),
  sshPort: z.coerce.number().int().positive().optional(),
  sshUser: z.string().optional(),
  sshKey: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

interface AnalysisFormProps {
  onStartAnalysis: (id: string) => void
}

const DB_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  sqlserver: 1433,
  oracle: 1521,
}

export function AnalysisForm({ onStartAnalysis }: AnalysisFormProps) {
  const [showSSH, setShowSSH] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      dbType: 'postgresql',
      dbPort: 5432,
      useSSH: false,
    }
  })

  const dbType = watch('dbType')

  const handleDbTypeChange = (type: string) => {
    setValue('dbType', type as FormData['dbType'])
    setValue('dbPort', DB_PORTS[type] || 5432)
  }

  const onSubmit = async (data: FormData) => {
    setIsLoading(true)
    try {
      const payload: Record<string, unknown> = {
        db_config: {
          type: data.dbType,
          host: data.dbHost,
          port: data.dbPort,
          database: data.dbName,
          user: data.dbUser,
          password: data.dbPassword,
        }
      }

      if (data.useSSH && data.sshHost) {
        payload.ssh_config = {
          host: data.sshHost,
          port: data.sshPort || 22,
          user: data.sshUser,
          key: data.sshKey,
        }
      }

      const res = await axios.post(`${API_URL}/api/analyze`, payload)
      onStartAnalysis(res.data.job_id)
      toast.success('Analysis started!')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start analysis'
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 max-w-2xl mx-auto">
      <div className="flex items-center mb-6">
        <Database className="h-6 w-6 text-indigo-600 dark:text-indigo-400 mr-2" />
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
          Connect Your Database
        </h2>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        {/* Database Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Database Type
          </label>
          <div className="grid grid-cols-4 gap-2">
            {['postgresql', 'mysql', 'sqlserver', 'oracle'].map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => handleDbTypeChange(type)}
                className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                  dbType === type
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {type === 'sqlserver' ? 'SQL Server' : type.charAt(0).toUpperCase() + type.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Connection Fields */}
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Host
            </label>
            <div className="relative">
              <Server className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
              <input
                {...register('dbHost')}
                placeholder="localhost or IP"
                className="w-full pl-9 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
            {errors.dbHost && <p className="text-red-500 text-xs mt-1">{errors.dbHost.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Port
            </label>
            <input
              {...register('dbPort')}
              type="number"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Database Name
          </label>
          <input
            {...register('dbName')}
            placeholder="my_database"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
          {errors.dbName && <p className="text-red-500 text-xs mt-1">{errors.dbName.message}</p>}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Username
            </label>
            <div className="relative">
              <Key className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
              <input
                {...register('dbUser')}
                placeholder="db_user"
                className="w-full pl-9 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
            {errors.dbUser && <p className="text-red-500 text-xs mt-1">{errors.dbUser.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Password
            </label>
            <input
              {...register('dbPassword')}
              type="password"
              placeholder="••••••••"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            {errors.dbPassword && <p className="text-red-500 text-xs mt-1">{errors.dbPassword.message}</p>}
          </div>
        </div>

        {/* SSH Toggle */}
        <button
          type="button"
          onClick={() => setShowSSH(!showSSH)}
          className="flex items-center text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {showSSH ? <ChevronUp className="h-4 w-4 mr-1" /> : <ChevronDown className="h-4 w-4 mr-1" />}
          SSH Tunnel (optional)
        </button>

        {showSSH && (
          <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">SSH Host</label>
                <input
                  {...register('sshHost')}
                  placeholder="ssh.server.com"
                  className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">SSH Port</label>
                <input
                  {...register('sshPort')}
                  type="number"
                  defaultValue={22}
                  className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">SSH User</label>
              <input
                {...register('sshUser')}
                placeholder="ubuntu"
                className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">SSH Private Key</label>
              <textarea
                {...register('sshKey')}
                rows={3}
                placeholder="-----BEGIN RSA PRIVATE KEY-----"
                className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm font-mono bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              />
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={isLoading}
          className="w-full flex items-center justify-center py-3 px-6 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-semibold rounded-xl transition-colors"
        >
          {isLoading ? (
            <span className="animate-spin mr-2">⟳</span>
          ) : (
            <Play className="h-5 w-5 mr-2" />
          )}
          {isLoading ? 'Starting Analysis...' : 'Start Analysis'}
        </button>
      </form>
    </div>
  )
}
