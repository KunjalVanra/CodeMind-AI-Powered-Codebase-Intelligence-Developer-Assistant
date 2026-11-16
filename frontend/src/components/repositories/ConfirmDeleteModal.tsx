import { AlertCircle, Trash2, X } from 'lucide-react'
import type { Repository } from '../../api/repositories'

type ConfirmDeleteModalProps = {
  repository: Repository
  isDeleting: boolean
  error: string | null
  onCancel: () => void
  onConfirm: () => void
}

function ConfirmDeleteModal({
  repository,
  isDeleting,
  error,
  onCancel,
  onConfirm,
}: ConfirmDeleteModalProps) {
  return (
    <div className="repository-modal-backdrop">
      <section
        className="repository-modal repository-delete-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-repository-title"
      >
        <div className="repository-modal-heading">
          <span className="repository-modal-icon repository-delete-icon">
            <Trash2 size={18} />
          </span>
          <button
            className="repository-modal-close"
            type="button"
            aria-label="Close dialog"
            onClick={onCancel}
            disabled={isDeleting}
          >
            <X size={18} />
          </button>
          <div>
            <h2 id="delete-repository-title">Delete repository?</h2>
            <p>
              Remove <strong>{repository.owner_name}/{repository.name}</strong> from
              this workspace. This action cannot be undone.
            </p>
          </div>
        </div>

        {error && (
          <div className="repository-form-error delete-error" role="alert">
            <AlertCircle size={15} />
            <span>{error}</span>
          </div>
        )}

        <div className="repository-modal-actions">
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={onCancel}
            disabled={isDeleting}
          >
            Cancel
          </button>
          <button
            className="repository-button repository-button-danger"
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? 'Deleting…' : 'Delete repository'}
          </button>
        </div>
      </section>
    </div>
  )
}

export default ConfirmDeleteModal
