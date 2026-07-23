import { motion } from 'motion/react'
import { ArrowRight, CheckCircle2, Eye, EyeOff, FlaskConical, LockKeyhole, Sparkles } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { apiErrorMessage } from '../lib/api'
import { Button, Input, Label } from '../components/ui'
import { toast } from 'sonner'

export function AuthPage({ mode = 'login' }: { mode?: 'login' | 'register' }) {
  const isRegister = mode === 'register'
  const navigate = useNavigate()
  const { login, register, loading } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (isRegister && password !== confirm) {
      toast.error('两次输入的密码不一致')
      return
    }
    try {
      if (isRegister) await register(email, password, fullName || undefined)
      else await login(email, password)
      toast.success(isRegister ? '账户已创建，欢迎进入研究空间' : '欢迎回来')
      navigate('/')
    } catch (error) {
      toast.error(apiErrorMessage(error, isRegister ? '注册未完成' : '登录未完成'))
    }
  }

  return (
    <div className="auth-page">
      <motion.div
        className="auth-layout"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
      >
        <section className="auth-story">
          <Link to="/login" className="auth-brand">
            <span className="brand-glyph">A</span>
            <span>
              <strong>Academic</strong>
              <em>Cluster</em>
            </span>
          </Link>
          <div className="auth-story-copy">
            <p className="eyebrow">RESEARCH, ORCHESTRATED</p>
            <h1>
              让复杂的研究，
              <br />
              <span>拥有清晰的轨迹。</span>
            </h1>
            <p>从问题定义到可引用的综述成果，每一个节点、来源和决策都被记录在你的研究空间里。</p>
          </div>
          <div className="auth-proof-row">
            <span>
              <CheckCircle2 size={15} />
              六节点工作流
            </span>
            <span>
              <CheckCircle2 size={15} />
              来源可追溯
            </span>
            <span>
              <CheckCircle2 size={15} />
              PostgreSQL checkpoint
            </span>
          </div>
        </section>
        <section className="auth-panel">
          <div className="auth-panel-header">
            <div className="auth-panel-icon">
              <FlaskConical size={19} />
            </div>
            <div>
              <p className="eyebrow">{isRegister ? 'CREATE SPACE' : 'WELCOME BACK'}</p>
              <h2>{isRegister ? '创建研究账户' : '进入研究空间'}</h2>
            </div>
          </div>
          <p className="auth-panel-detail">
            {isRegister ? '建立你的个人研究空间，随时继续未完成的工作。' : '登录后继续探索你的项目、证据和执行轨迹。'}
          </p>
          <form className="auth-form" onSubmit={submit}>
            {isRegister && (
              <div className="field-group">
                <Label htmlFor="full-name">姓名</Label>
                <Input
                  id="full-name"
                  autoComplete="name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="例如：林夏"
                />
              </div>
            )}
            <div className="field-group">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@research.org"
              />
            </div>
            <div className="field-group">
              <Label htmlFor="password">密码</Label>
              <div className="password-input">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                  required
                  minLength={isRegister ? 12 : 1}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={isRegister ? '至少 12 个字符' : '输入密码'}
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            {isRegister && (
              <div className="field-group">
                <Label htmlFor="confirm-password">确认密码</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={12}
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  placeholder="再次输入密码"
                />
              </div>
            )}
            <Button type="submit" size="lg" className="auth-submit" disabled={loading}>
              {loading ? (
                <span className="button-loading">
                  <span />
                  处理中…
                </span>
              ) : (
                <>
                  {isRegister ? '创建账户' : '登录'}
                  <ArrowRight size={17} />
                </>
              )}
            </Button>
          </form>
          <div className="auth-switch">
            {isRegister ? '已经有账户？' : '还没有研究账户？'}{' '}
            <Link to={isRegister ? '/login' : '/register'}>
              {isRegister ? '返回登录' : '创建一个'} <ArrowRight size={13} />
            </Link>
          </div>
          <div className="auth-security">
            <LockKeyhole size={13} />
            你的凭证通过 Bearer token 与 refresh rotation 保护
          </div>
        </section>
      </motion.div>
      <div className="auth-footer">
        <Sparkles size={13} /> Academic Cluster · research workspace
      </div>
    </div>
  )
}
