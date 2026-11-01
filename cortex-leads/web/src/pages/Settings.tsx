import { PageHeader } from '../components/ui'
import { GoogleSection } from './Google'

export function Settings() {
  return (
    <div className="flex h-full flex-col gap-8 overflow-y-auto p-8">
      <PageHeader title="Cài đặt" subtitle="Những kết nối của doanh nghiệp với bên ngoài." />
      <GoogleSection />
    </div>
  )
}
